"""DeepSeek API 摘要模块 — 每领域一次调用，生成结构化摘要"""

import json
import logging
import time
from typing import Optional

from openai import OpenAI

from .config import load_config, load_api_key
from .models import Article, CategoryDigest, DigestItem

logger = logging.getLogger("eyes.summarize")

SYSTEM_PROMPT = """你是「新闻之眼」首席中文编辑。把原始新闻加工成精炼、客观、可读的中文每日简报。

编辑原则：
1. 全部输出简体中文。英文来源翻译为中文，但保留原文标题并标注来源
2. 客观中立，军事和政治类只做事实陈述，不渲染冲突细节
3. 每条新闻给出简洁标题改写 + 2-3句核心要点
4. 按重要性排序，跨源重复报道只保留最重要的一条
5. 不添加新闻来源之外的信息，存疑处标注"待核实"
6. 每条标注来源媒体名称和原文链接
7. 请以 JSON 格式输出结果

你是读者的眼睛，帮助他们高效了解今天发生了什么。"""

CATEGORY_DESCRIPTIONS = {
    "科技": "互联网、人工智能、硬件、航天、生物技术等科技领域的最新动态",
    "金融": "股市、宏观经济、加密货币、企业财报、货币政策等财经资讯",
    "文化": "影视、文学、艺术、音乐、时尚、设计等文化领域动态",
    "民生": "社会热点、教育、医疗、环境、住房等民生相关新闻",
    "军事": "国际军事动态、地缘冲突、国防政策、军事科技",
    "政治": "国内外政策法规、外交关系、选举政治、国际局势",
    "全球会议与重大活动": "联合国、G20、APEC、气候峰会等国际会议，以及奥运会、世界杯等重大全球活动",
}


def _build_client() -> OpenAI:
    """构建 DeepSeek 客户端"""
    cfg = load_config()
    return OpenAI(
        api_key=load_api_key(),
        base_url=cfg["api"]["base_url"],
    )


def _build_user_message(category: str, articles: list[Article], max_items: int) -> str:
    """构建单领域 user message"""
    desc = CATEGORY_DESCRIPTIONS.get(category, category)
    lines = [
        f"## 领域：{category}",
        f"说明：{desc}",
        f"以下是今天抓取到的 {len(articles)} 条候选新闻。请从中选出最重要的 {max_items} 条，去重合并后生成摘要。\n\n"
        f"请严格按以下JSON格式返回（不要修改字段名）：\n"
        f'{{"digest": "该领域一句话概述", "items": [{{"title": "...", "summary": "...", "source": "...", "link": "..."}}]}}',
        "",
    ]

    for i, a in enumerate(articles, 1):
        pub_str = a.published.strftime("%Y-%m-%d %H:%M") if a.published else "未知时间"
        lines.append(f"[{i}] {a.title}")
        lines.append(f"    来源：{a.source_name} | 时间：{pub_str} | 语言：{a.lang}")
        lines.append(f"    链接：{a.url}")
        if a.summary:
            lines.append(f"    摘要：{a.summary[:300]}")
        lines.append("")

    return "\n".join(lines)


def _summarize_category(client: OpenAI, cfg: dict, category: str,
                        articles: list[Article]) -> CategoryDigest:
    """对单个领域调用 DeepSeek 生成摘要"""
    model = cfg["api"]["model"]
    max_tokens = cfg["api"]["max_tokens"]
    temperature = cfg["api"]["temperature"]
    max_items = cfg["summary"]["max_articles_per_category"]

    if not articles:
        return CategoryDigest(
            category=category,
            digest="今日无更新",
            items=[],
        )

    user_msg = _build_user_message(category, articles, max_items)

    json_schema = {"type": "json_object"}

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
            response_format=json_schema,
        )

        content = resp.choices[0].message.content
        if not content:
            raise ValueError("API 返回空内容")

        data = json.loads(content)

        # 灵活解析：适配不同的字段名
        # digest 可能在 digest / summary / overview 字段
        digest_text = (
            data.get("digest") or data.get("summary") or
            data.get("overview") or ""
        )

        # items 可能在 items / news / articles / results 字段
        raw_items = (
            data.get("items") or data.get("news") or
            data.get("articles") or data.get("results") or []
        )

        items = [
            DigestItem(
                title=item.get("title", ""),
                summary=item.get("summary", item.get("description", "")),
                source=item.get("source", item.get("origin", "")),
                link=item.get("link", item.get("url", "")),
            )
            for item in raw_items
        ]

        logger.info(f"  ✓ {category}: {len(items)} 条摘要")
        return CategoryDigest(
            category=category,
            digest=digest_text,
            items=items,
        )

    except Exception as e:
        logger.warning(f"  ✗ {category} 摘要失败: {e}")
        # 降级：直接列出原始标题
        fallback_items = [
            DigestItem(
                title=a.title,
                summary=a.summary[:200] if a.summary else "",
                source=a.source_name,
                link=a.url,
            )
            for a in articles[:max_items]
        ]
        return CategoryDigest(
            category=category,
            digest=f"{category}今日动态（API调用失败，以下为原始标题列表）",
            items=fallback_items,
            error=str(e),
        )


def summarize_all(articles_by_category: dict[str, list[Article]]) -> list[CategoryDigest]:
    """对所有领域依次生成摘要"""
    cfg = load_config()
    client = _build_client()

    logger.info(f"开始摘要生成，模型={cfg['api']['model']}，领域数={len(articles_by_category)}")

    results = []
    for category, articles in articles_by_category.items():
        # DeepSeek 有速率限制，简单延时
        if results:  # 非第一个，稍等
            time.sleep(1)

        result = _summarize_category(client, cfg, category, articles)
        results.append(result)

    total_items = sum(len(r.items) for r in results)
    errors = sum(1 for r in results if r.error)
    logger.info(f"摘要完成: {total_items} 条, {errors} 个领域降级")
    return results
