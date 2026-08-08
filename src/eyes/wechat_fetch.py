"""微信公众号文章抓取模块

通过搜狗微信搜索发现文章链接，然后抓取 mp.weixin.qq.com 文章全文。

抓取流程：
1. 首次访问搜狗首页获取 Cookie
2. 用 type=2 搜索公众号名称，获取近期文章列表
3. 跟随搜狗重定向链接，获取真正的 mp.weixin.qq.com URL
4. 抓取文章页面全文
"""

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
from bs4 import BeautifulSoup

from .models import WechatArticle

logger = logging.getLogger("eyes.wechat")

CHINA_TZ = timezone(timedelta(hours=8))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

SOGOU_HOME = "https://weixin.sogou.com/"
SOGOU_SEARCH = "https://weixin.sogou.com/weixin"

# 搜狗 script 中的 Unix 时间戳
_TIMESTAMP_RE = re.compile(r"timeConvert\('(\d+)'\)")


def _init_session() -> requests.Session:
    """创建 session 并初始化搜狗 Cookie"""
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        session.get(SOGOU_HOME, timeout=10)
    except Exception:
        pass
    return session


def _extract_timestamp(script_text: str) -> Optional[int]:
    """从搜狗的时间戳 script 中提取 Unix 时间戳"""
    m = _TIMESTAMP_RE.search(script_text)
    if m:
        return int(m.group(1))
    return None


def _ts_to_datetime(ts: int) -> datetime:
    """Unix 时间戳转中国时区 datetime"""
    return datetime.fromtimestamp(ts, tz=CHINA_TZ)


def _resolve_sogou_url(sogou_link: str, session: requests.Session, timeout: int = 15) -> Optional[str]:
    """跟随搜狗 /link?url=... 重定向，获取真实的 mp.weixin.qq.com URL"""
    if "mp.weixin.qq.com" in sogou_link:
        return sogou_link

    url = sogou_link
    if url.startswith("/"):
        url = "https://weixin.sogou.com" + url

    try:
        headers = {**HEADERS, "Referer": "https://weixin.sogou.com/"}
        resp = session.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        if "mp.weixin.qq.com" in resp.url:
            return resp.url

        # 有些情况搜狗返回中间页，需要提取
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if "mp.weixin.qq.com" in href:
                return href
        for meta in soup.select("meta[http-equiv='refresh']"):
            content = meta.get("content", "")
            m = re.search(r"url=(\S+)", content, re.I)
            if m and "mp.weixin.qq.com" in m.group(1):
                return m.group(1)
    except Exception as e:
        logger.debug(f"  解析重定向失败: {e}")
    return None


def search_sogou(account_name: str, session: requests.Session,
                 pages: int = 2, timeout: int = 15) -> list[dict]:
    """通过搜狗微信搜索发现文章列表（支持翻页）

    返回 [{title, link(sogou redirect), account, ts(datetime), summary}, ...]
    """
    all_articles: list[dict] = []

    for page in range(1, pages + 1):
        params = {"type": "2", "query": account_name, "ie": "utf8", "page": str(page)}
        try:
            resp = session.get(SOGOU_SEARCH, params=params, timeout=timeout)
            resp.raise_for_status()
        except Exception as e:
            logger.warning(f"  搜狗搜索失败 '{account_name}' p{page}: {e}")
            continue

        text = resp.text

        if "请输入验证码" in text or "antispider" in text.lower():
            logger.warning(f"  搜狗触发反爬: {account_name} p{page}")
            break

        soup = BeautifulSoup(text, "html.parser")
        page_articles = 0

        for li in soup.select("ul.news-list li"):
            try:
                title_a = li.select_one(".txt-box h3 a")
                if not title_a:
                    continue
                title = title_a.get_text(strip=True)
                link = title_a.get("href", "")
                if not link:
                    continue

                summary_el = li.select_one(".txt-box p")
                summary = summary_el.get_text(strip=True) if summary_el else ""

                account_el = li.select_one(".s-p .all-time-y2, .s-p span:first-of-type")
                result_account = account_el.get_text(strip=True) if account_el else ""

                date_script = li.select_one(".s-p .s2 script")
                ts = None
                if date_script:
                    ts = _extract_timestamp(date_script.get_text(strip=True))
                if ts is None:
                    date_span = li.select_one(".s-p .s2")
                    if date_span:
                        date_text = date_span.get_text(strip=True)
                        if date_text.isdigit():
                            ts = int(date_text)

                pub_dt = _ts_to_datetime(ts) if ts else None

                all_articles.append({
                    "title": title,
                    "link": link,
                    "account": result_account,
                    "ts": pub_dt,
                    "summary": summary,
                })
                page_articles += 1
            except Exception as e:
                logger.debug(f"  解析条目失败: {e}")
                continue

        # 如果当前页全是无关账号的文章，停止翻页
        if page_articles == 0:
            break
        if page < pages:
            time.sleep(0.5)

    # 按时间倒序排列
    all_articles.sort(key=lambda a: a.get("ts") or datetime(2000, 1, 1, tzinfo=CHINA_TZ), reverse=True)

    logger.info(f"  搜狗 '{account_name}': 发现 {len(all_articles)} 条 ({pages}页)")
    return all_articles


def fetch_article(url: str, session: requests.Session, timeout: int = 15) -> Optional[WechatArticle]:
    """抓取单篇公众号文章全文"""
    try:
        resp = session.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
    except Exception as e:
        logger.debug(f"  抓取文章失败 {url[:60]}...: {e}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    # 标题
    title = ""
    for sel in ["#activity-name", ".rich_media_title", "h1.rich_media_title"]:
        tag = soup.select_one(sel)
        if tag:
            title = tag.get_text(strip=True)
            break
    if not title:
        title = "未知标题"

    # 公众号名称
    account = ""
    for sel in ["#js_name", ".rich_media_meta_nickname"]:
        tag = soup.select_one(sel)
        if tag:
            account = tag.get_text(strip=True)
            break

    # 发布日期
    date_str = ""
    for sel in ["#publish_time", ".rich_media_meta_text"]:
        tag = soup.select_one(sel)
        if tag:
            date_str = tag.get_text(strip=True)
            break

    # 正文
    content = ""
    for sel in ["#js_content", ".rich_media_content"]:
        tag = soup.select_one(sel)
        if tag:
            # 移除隐藏元素
            for hidden in tag.select(
                "[style*='display:none'], [style*='display: none'], "
                "[style*='visibility:hidden'], [style*='visibility: hidden'], "
                "script, style, .reward_area, .qr_code_pc, mpa-style-panel"
            ):
                hidden.decompose()
            # 图片替换为占位符
            for img in tag.select("img"):
                alt = img.get("alt", "")
                if alt:
                    img.replace_with(f"[图: {alt}]")
                else:
                    img.decompose()
            content = tag.get_text(separator="\n", strip=True)
            break

    if not content:
        logger.debug(f"  未找到正文: {title}")
        return None

    content = re.sub(r"\n{3,}", "\n\n", content)
    content = re.sub(r"[ \t]{2,}", " ", content)

    return WechatArticle(
        title=title,
        url=url,
        account=account,
        date_str=date_str,
        content=content,
    )


def fetch_account_articles(
    account_name: str,
    session: requests.Session,
    max_days: int = 1,
    max_articles: int = 5,
    search_pages: int = 2,
    timeout: int = 15,
) -> list[WechatArticle]:
    """抓取指定公众号近期文章"""
    logger.info(f"🔍 抓取公众号: {account_name}")

    # 1. 搜狗搜索（翻页）
    raw = search_sogou(account_name, session, pages=search_pages, timeout=timeout)
    if not raw:
        logger.warning(f"  ✗ {account_name}: 未发现任何文章")
        return []

    # 按账号名称过滤：只保留发布者名称包含搜索关键词的结果
    matched = [a for a in raw if account_name in a.get("account", "")]
    if len(matched) < len(raw):
        logger.info(f"  账号过滤: {len(raw)} → {len(matched)} (匹配 '{account_name}')")
    raw = matched

    if not raw:
        logger.info(f"  - {account_name}: 无匹配账号的文章")
        return []

    # 2. 日期过滤
    cutoff = datetime.now(CHINA_TZ) - timedelta(days=max_days)
    recent = [a for a in raw if a.get("ts") and a["ts"] >= cutoff]
    no_date = [a for a in raw if a.get("ts") is None]
    recent = recent + no_date[:2]

    if len(recent) < len(raw):
        logger.info(f"  日期过滤: {len(raw)} → {len(recent)} (最近{max_days}天)")

    if not recent:
        logger.info(f"  - {account_name}: 最近{max_days}天无新文章")
        return []

    # 3. 构建文章对象（使用搜狗摘要作为内容，搜狗跳转链接作为文章链接）
    #    注：搜狗反爬阻止了重定向链解析，无法获取 mp.weixin.qq.com 直链
    #    搜狗跳转链接在用户浏览器中可正常跳转到微信原文
    articles = []
    for item in recent[:max_articles]:
        sogou_link = item["link"]
        if sogou_link.startswith("/"):
            sogou_link = "https://weixin.sogou.com" + sogou_link

        date_str = item["ts"].strftime("%Y-%m-%d %H:%M") if item.get("ts") else ""

        article = WechatArticle(
            title=item["title"],
            url=sogou_link,
            account=item.get("account", account_name),
            date_str=date_str,
            content=item.get("summary", ""),
        )
        articles.append(article)
        logger.info(f"  ✓ {article.title[:40]}... ({len(article.content)} 字摘要)")

    logger.info(f"  {account_name}: 成功获取 {len(articles)} 篇")
    return articles


def fetch_all_accounts(
    accounts: list[str],
    max_days: int = 1,
    max_per_account: int = 5,
    search_pages: int = 2,
    timeout: int = 15,
) -> dict[str, list[WechatArticle]]:
    """批量抓取多个公众号文章"""
    session = _init_session()

    results: dict[str, list[WechatArticle]] = {}
    for i, account in enumerate(accounts):
        if i > 0:
            time.sleep(2)
        try:
            articles = fetch_account_articles(
                account, session,
                max_days=max_days,
                max_articles=max_per_account,
                search_pages=search_pages,
                timeout=timeout,
            )
            results[account] = articles
        except Exception as e:
            logger.warning(f"抓取 {account} 异常: {e}")
            results[account] = []

    session.close()

    total = sum(len(v) for v in results.values())
    logger.info(f"全部抓取完成: {total} 篇文章")
    return results
