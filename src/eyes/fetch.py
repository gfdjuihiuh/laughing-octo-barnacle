"""RSS 抓取模块 — 并发抓取所有新闻源"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Optional

import feedparser
import requests

from .config import load_config
from .models import Article

logger = logging.getLogger("eyes.fetch")

# 请求 headers，避免被部分站点拒绝
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
}


def _build_session() -> requests.Session:
    """构建带代理的 requests Session"""
    import os
    cfg = load_config()
    session = requests.Session()
    session.headers.update(HEADERS)
    # 环境变量 EYES_PROXY 可覆盖代理设置（GitHub Actions 设为空禁用代理）
    proxy_url = os.getenv("EYES_PROXY", cfg["fetch"].get("proxy", ""))
    if proxy_url:
        session.proxies = {"http": proxy_url, "https": proxy_url}
        logger.debug(f"使用代理: {proxy_url}")
    return session


# 模块级 session（线程安全）
_SESSION = None


def _get_session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        _SESSION = _build_session()
    return _SESSION


def _fetch_single(source: dict, lookback_hours: int, timeout: int, max_retries: int) -> list[Article]:
    """抓取单个 RSS 源，返回 Article 列表。失败返回空列表。"""
    url = source["url"]
    name = source["name"]
    session = _get_session()

    for attempt in range(max_retries + 1):
        try:
            resp = session.get(url, timeout=timeout)
            resp.raise_for_status()
            # feedparser 可以直接解析字符串
            feed = feedparser.parse(resp.content)
            break
        except requests.RequestException as e:
            if attempt < max_retries:
                logger.debug(f"重试 {name}: 第 {attempt+1} 次失败 — {e}")
            else:
                logger.warning(f"抓取失败 {name}: {e}")
                return []
        except Exception as e:
            logger.warning(f"解析失败 {name}: {e}")
            return []
    else:
        return []  # 不应该到这里

    if feed.bozo and not feed.entries:
        logger.warning(f"RSS 解析异常 {name}: {feed.bozo_exception}")
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    articles = []

    for entry in feed.entries:
        # 解析发布时间
        published = None
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            try:
                published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pass
        if published is None and hasattr(entry, "updated_parsed") and entry.updated_parsed:
            try:
                published = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pass

        # 时间窗口过滤
        if published is not None and published < cutoff:
            continue

        # 提取摘要/正文
        summary = ""
        if hasattr(entry, "summary"):
            summary = _strip_html(entry.summary)
        elif hasattr(entry, "description"):
            summary = _strip_html(entry.description)

        content = ""
        if hasattr(entry, "content") and entry.content:
            content = _strip_html(entry.content[0].get("value", ""))
        if not content:
            content = summary

        # 正文截断
        content_truncate = load_config().get("summary", {}).get("content_truncate_chars", 600)
        content = content[:content_truncate]
        summary = summary[:content_truncate]

        articles.append(Article(
            title=getattr(entry, "title", "无标题").strip(),
            url=getattr(entry, "link", ""),
            source_name=name,
            source_url=url,
            category=source["category"],
            lang=source.get("lang", "zh"),
            published=published,
            summary=summary,
            content=content,
        ))

    if articles:
        logger.info(f"  ✓ {name}: {len(articles)} 条")
    else:
        logger.info(f"  - {name}: 0 条（窗口内无更新）")
    return articles


def _strip_html(text: str) -> str:
    """简易 HTML 标签去除"""
    import re
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fetch_all(sources: dict[str, list[dict]]) -> list[Article]:
    """并发抓取所有已启用的新闻源"""
    cfg = load_config()
    lookback = cfg["fetch"]["lookback_hours"]
    timeout = cfg["fetch"]["timeout_seconds"]
    max_retries = cfg["fetch"]["max_retries"]
    max_workers = cfg["fetch"]["max_workers"]

    # 展开所有源为扁平列表
    all_sources = []
    for category, src_list in sources.items():
        for src in src_list:
            all_sources.append({**src, "category": category})

    logger.info(f"开始抓取 {len(all_sources)} 个新闻源 (窗口={lookback}h, 并发={max_workers})")

    articles = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_fetch_single, src, lookback, timeout, max_retries): src
            for src in all_sources
        }
        for future in as_completed(futures):
            try:
                articles.extend(future.result())
            except Exception as e:
                src = futures[future]
                logger.warning(f"未预期的抓取错误 {src['name']}: {e}")

    logger.info(f"抓取完成: 共 {len(articles)} 条原始文章")
    return articles


def check_sources(sources: dict[str, list[dict]]) -> None:
    """健康检查所有新闻源（--check-sources 命令）"""
    from rich.console import Console
    from rich.table import Table

    console = Console()
    table = Table(title="新闻源健康检查")
    table.add_column("领域", style="cyan")
    table.add_column("名称", style="green")
    table.add_column("状态", style="bold")
    table.add_column("详情")

    for category, src_list in sources.items():
        for src in src_list:
            try:
                resp = _get_session().get(src["url"], timeout=15)
                if resp.ok:
                    feed = feedparser.parse(resp.content)
                    if feed.entries:
                        table.add_row(category, src["name"], "[green]✓ 正常[/]", f"{len(feed.entries)} 条")
                    else:
                        table.add_row(category, src["name"], "[yellow]⚠ 空[/]", "RSS 无条目或解析失败")
                else:
                    table.add_row(category, src["name"], "[red]✗ 失败[/]", f"HTTP {resp.status_code}")
            except requests.Timeout:
                table.add_row(category, src["name"], "[red]✗ 超时[/]", ">15s")
            except Exception as e:
                table.add_row(category, src["name"], "[red]✗ 错误[/]", str(e)[:60])

    console.print(table)
