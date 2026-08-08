"""微信文章摘要与报告生成模块

对每篇文章通过 DeepSeek 进行关键点提炼，
生成结构化日报并推送到微信。
"""

import json
import logging
import time
from datetime import datetime, timedelta, timezone

from openai import OpenAI

from .config import load_config, load_api_key
from .models import WechatArticle
from .push import push_to_pushplus

logger = logging.getLogger("eyes.wechat_report")

CHINA_TZ = timezone(timedelta(hours=8))

SUMMARIZE_SYSTEM = """你是资深财经信息分析师。对微信公众号文章提炼核心要点。

规则：
1. 提取 3-5 条核心要点，每条一句话（25字以内）
2. 重点抓：操作建议、关键数据、板块方向、风险提示
3. 如果是复盘类文章，提炼当日操作逻辑
4. 客观提炼，不添加原文没有的信息
5. 按 JSON 格式输出

输出格式：
{"points": ["要点1", "要点2", "要点3"], "one_line": "一句话总结（30字以内）"}
"""


def _build_client() -> OpenAI:
    cfg = load_config()
    return OpenAI(
        api_key=load_api_key(),
        base_url=cfg["api"]["base_url"],
    )


def summarize_article(article: WechatArticle, client: OpenAI, cfg: dict) -> WechatArticle:
    """对单篇文章提取核心要点"""
    # 正文截断（控制 token 消耗）
    max_chars = cfg.get("summary", {}).get("content_truncate_chars", 600)
    content_snippet = article.content[:max_chars * 2]  # 微信文章给更多空间

    user_msg = f"""请分析以下微信公众号文章，提取核心要点。

公众号：{article.account}
标题：{article.title}
发布日期：{article.date_str}

正文（截取）：
{content_snippet[:2500]}
"""

    try:
        resp = client.chat.completions.create(
            model=cfg["api"]["model"],
            messages=[
                {"role": "system", "content": SUMMARIZE_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=cfg["api"].get("max_tokens", 2048),
            temperature=0.3,
            response_format={"type": "json_object"},
        )

        raw = resp.choices[0].message.content
        if not raw:
            raise ValueError("API 返回空内容")

        data = json.loads(raw)
        points = data.get("points", [])
        one_line = data.get("one_line", "")

        # 格式化为摘要文本
        summary = ""
        if one_line:
            summary = f"📌 {one_line}\n\n"
        if points:
            summary += "\n".join(f"• {p}" for p in points)

        article.summary = summary
        logger.info(f"  ✓ 摘要完成: {article.title[:30]}...")

    except Exception as e:
        logger.warning(f"  ✗ 摘要失败 '{article.title[:30]}...': {e}")
        # 降级：用前200字作为摘要
        article.summary = article.content[:200] + "..."

    return article


def summarize_all_articles(
    articles_by_account: dict[str, list[WechatArticle]],
    delay: float = 1.0,
) -> dict[str, list[WechatArticle]]:
    """对所有文章进行摘要"""
    cfg = load_config()
    client = _build_client()

    total = sum(len(v) for v in articles_by_account.values())
    if total == 0:
        logger.info("无文章需要摘要")
        return articles_by_account

    logger.info(f"开始摘要 {total} 篇文章 (模型={cfg['api']['model']})")

    count = 0
    for account, articles in articles_by_account.items():
        for article in articles:
            if count > 0:
                time.sleep(delay)
            summarize_article(article, client, cfg)
            count += 1

    logger.info(f"摘要完成: {total} 篇")
    return articles_by_account


def build_html_report(
    articles_by_account: dict[str, list[WechatArticle]],
    date_str: str,
) -> str:
    """构建 HTML 格式的日报（适配 PushPlus 微信推送）

    返回可直接作为 PushPlus content 的 HTML 字符串
    """
    total = sum(len(v) for v in articles_by_account.values())

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; padding: 12px; }}
.header {{ text-align: center; margin-bottom: 16px; }}
.header h2 {{ margin: 0; font-size: 18px; }}
.header p {{ color: #888; font-size: 12px; margin: 4px 0 0; }}
.account-section {{ margin-bottom: 16px; }}
.account-title {{ font-size: 16px; font-weight: bold; padding: 8px 12px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: #fff; border-radius: 8px 8px 0 0; }}
.article {{ border: 1px solid #e0e0e0; border-top: none; padding: 10px; }}
.article:last-of-type {{ border-radius: 0 0 8px 8px; }}
.article-title {{ font-size: 14px; font-weight: bold; color: #333; margin-bottom: 6px; }}
.article-title a {{ color: #333; text-decoration: none; }}
.article-title a:hover {{ color: #667eea; }}
.article-meta {{ font-size: 11px; color: #999; margin-bottom: 6px; }}
.article-summary {{ font-size: 13px; color: #555; line-height: 1.6; white-space: pre-line; }}
.footer {{ text-align: center; font-size: 11px; color: #bbb; margin-top: 20px; padding-top: 12px; border-top: 1px solid #eee; }}
.empty {{ text-align: center; color: #999; padding: 20px; font-size: 14px; }}
</style>
</head>
<body>
<div class="header">
<h2>📊 微信公众号日报</h2>
<p>{date_str} · 共 {total} 篇</p>
</div>
"""

    if total == 0:
        html += '<div class="empty">今日无新文章 📭</div>'
    else:
        for account, articles in articles_by_account.items():
            if not articles:
                continue
            html += f'<div class="account-section">\n'
            html += f'<div class="account-title">📌 {account} ({len(articles)}篇)</div>\n'
            for article in articles:
                summary_html = article.summary.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
                title_html = article.title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                html += f"""<div class="article">
<div class="article-title"><a href="{article.url}">{title_html}</a></div>
<div class="article-meta">{article.date_str}</div>
<div class="article-summary">{summary_html}</div>
</div>
"""
            html += '</div>\n'

    html += f"""
<div class="footer">
🧿 新闻之眼 · 自动生成于 {datetime.now(CHINA_TZ).strftime("%H:%M")}
</div>
</body>
</html>"""

    return html


def build_text_report(
    articles_by_account: dict[str, list[WechatArticle]],
    date_str: str,
) -> str:
    """构建纯文本格式日报（调试/日志用）"""
    total = sum(len(v) for v in articles_by_account.values())
    lines = [
        f"📊 微信公众号日报 · {date_str}",
        f"{'─' * 30}",
        "",
    ]

    if total == 0:
        lines.append("今日无新文章")
    else:
        for account, articles in articles_by_account.items():
            if not articles:
                continue
            lines.append(f"📌 {account} ({len(articles)}篇)")
            lines.append("")
            for i, article in enumerate(articles, 1):
                lines.append(f"  {i}. {article.title}")
                # 截断长链接显示
                url_display = article.url if len(article.url) < 80 else article.url[:77] + "..."
                lines.append(f"     {url_display}")
                if article.summary:
                    lines.append(f"     {article.summary}")
                lines.append("")
            lines.append("")

    lines.append(f"🧿 新闻之眼 · 自动生成")
    return "\n".join(lines)
