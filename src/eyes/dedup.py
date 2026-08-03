"""去重模块 — URL归一化 + bigram Jaccard 标题相似度去重"""

import hashlib
import json
import logging
import re
from collections import OrderedDict
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

from .config import PROJECT_ROOT, load_config
from .models import Article

logger = logging.getLogger("eyes.dedup")

# 常见的追踪参数
TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "ref", "source", "utm_id", "mc_cid", "mc_eid",
    "_ga", "_gl", "pk_source", "pk_medium", "pk_campaign",
}


def normalize_url(url: str) -> str:
    """URL 归一化：去追踪参数、去 fragment、小写 host"""
    try:
        parsed = urlparse(url)
        # 去追踪参数
        query_params = parse_qs(parsed.query, keep_blank_values=False)
        cleaned = {k: v for k, v in query_params.items()
                   if k.lower() not in TRACKING_PARAMS}
        new_query = urlencode(cleaned, doseq=True) if cleaned else ""

        normalized = urlunparse((
            parsed.scheme,
            parsed.hostname.lower() if parsed.hostname else "",
            parsed.path.rstrip("/") or "/",
            parsed.params,
            new_query,
            "",  # 去掉 fragment
        ))
        return normalized
    except Exception:
        return url


def _bigrams(text: str) -> set[str]:
    """中文友好：字符二元组。对英文单词也适用。"""
    text = text.lower().strip()
    chars = list(text)
    if len(chars) < 2:
        return {text} if text else set()
    return {chars[i] + chars[i + 1] for i in range(len(chars) - 1)}


def _title_similarity(title1: str, title2: str) -> float:
    """bigram Jaccard 相似度"""
    b1 = _bigrams(title1)
    b2 = _bigrams(title2)
    if not b1 or not b2:
        return 0.0
    intersection = len(b1 & b2)
    union = len(b1 | b2)
    return intersection / union if union > 0 else 0.0


def deduplicate(articles: list[Article]) -> list[Article]:
    """对文章列表去重：URL归一化 + 标题相似度"""
    cfg = load_config()
    threshold = cfg["dedup"]["title_similarity_threshold"]
    seen_urls: set[str] = set()
    kept: list[Article] = []

    for article in articles:
        norm_url = normalize_url(article.url)

        # URL 完全相同 → 跳过
        if norm_url in seen_urls:
            continue

        # 标题相似度检查
        is_dup = False
        for existing in kept:
            sim = _title_similarity(article.title, existing.title)
            if sim >= threshold:
                logger.debug(f"标题去重: '{article.title[:40]}' ≈ '{existing.title[:40]}' ({sim:.2f})")
                is_dup = True
                break

        if not is_dup:
            seen_urls.add(norm_url)
            kept.append(article)

    logger.info(f"去重: {len(articles)} → {len(kept)} 条")
    return kept


def cross_day_filter(articles: list[Article]) -> list[Article]:
    """跨日去重：排除之前日期已见过的 URL hash，同一天的不去重"""
    cfg = load_config()
    if not cfg["dedup"]["enable_cross_day_dedup"]:
        return articles

    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    state_file = PROJECT_ROOT / cfg["dedup"]["seen_state_file"]
    prior_hashes = _load_prior_hashes(state_file, today)

    filtered = []
    today_hashes = set()
    for a in articles:
        h = hashlib.md5(normalize_url(a.url).encode()).hexdigest()
        if h in prior_hashes:
            logger.debug(f"跨日去重跳过: {a.title[:40]}")
            continue
        today_hashes.add(h)
        filtered.append(a)

    # 保存今天见过的 hash（加上日期标记）
    _save_today_hashes(state_file, today, today_hashes)

    if len(filtered) < len(articles):
        logger.info(f"跨日去重: {len(articles)} → {len(filtered)} 条")
    return filtered


def _load_prior_hashes(state_file: Path, today: str) -> set[str]:
    """加载之前日期的 URL hash（排除今天的）"""
    if not state_file.exists():
        return set()
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
        prior = set()
        for date_key, hashes in data.items():
            if date_key != today:  # 只加载非今天的
                prior.update(hashes)
        return prior
    except (json.JSONDecodeError, AttributeError):
        return set()


def _save_today_hashes(state_file: Path, today: str, hashes: set[str]) -> None:
    """保存今天的 URL hash，清理 7 天前的旧数据"""
    state_file.parent.mkdir(parents=True, exist_ok=True)

    data = {}
    if state_file.exists():
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}

    # 只保留最近 7 天的
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    data = {k: v for k, v in data.items() if k >= cutoff}

    # 写入今天的
    data[today] = list(hashes)

    state_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def filter_by_category_events(articles: list[Article]) -> list[Article]:
    """从所有文章中提取与'全球会议与重大活动'相关的条目"""
    keywords = [
        "峰会", "论坛", "大会", "会议", "开幕式", "闭幕",
        "COP", "G7", "G20", "UNGA", "BRICS", "APEC",
        "summit", "forum", "conference", "general assembly",
        "Olympic", "World Cup", "世博", "奥运", "世界杯",
        "气候", "贸易协定", "首脑", "外长", "宣言",
    ]
    pattern = re.compile("|".join(keywords), re.IGNORECASE)

    events = []
    for a in articles:
        text = f"{a.title} {a.summary}"
        if pattern.search(text):
            events.append(a)

    logger.info(f"会议活动关键词过滤: {len(events)} 条候选")
    return events
