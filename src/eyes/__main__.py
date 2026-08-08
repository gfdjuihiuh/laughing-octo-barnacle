"""python -m eyes 入口"""

import logging
import sys
from collections import OrderedDict
from datetime import datetime, timedelta, timezone

# 中国时区 UTC+8
CHINA_TZ = timezone(timedelta(hours=8))

from .cli import build_parser, parse_categories
from .config import VALID_CATEGORIES, load_config, load_sources
from .fetch import check_sources, fetch_all
from .dedup import cross_day_filter, deduplicate, filter_by_category_events
from .logging_setup import setup_logging
from .models import DailyReport
from .push import push_to_pushplus, push_to_wechat
from .report import print_to_terminal, render_news_html, write_report
from .summarize import summarize_all

logger = logging.getLogger("eyes")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # --wechat 模式
    if args.wechat:
        main_wechat()
        return

    # 日志
    cfg = load_config()
    log_level = "DEBUG" if args.verbose else cfg["logging"]["level"]
    setup_logging(level=log_level, log_file=cfg["logging"]["log_file"])

    logger.info("🧿 新闻之眼启动")

    # --check-sources 模式
    if args.check_sources:
        sources = load_sources()
        check_sources(sources)
        return

    # 确定日期
    if args.date:
        try:
            report_date = args.date
            datetime.strptime(report_date, "%Y-%m-%d")
        except ValueError:
            print(f"错误：日期格式无效 '{args.date}'，应为 YYYY-MM-DD", file=sys.stderr)
            sys.exit(1)
    else:
        report_date = datetime.now(CHINA_TZ).strftime("%Y-%m-%d")

    # 加载配置
    sources = load_sources()
    categories = parse_categories(args.category)
    if categories is not None:
        sources = {k: v for k, v in sources.items() if k in categories}
        logger.info(f"限定领域: {', '.join(categories)}")

    # 1. 抓取
    articles = fetch_all(sources)
    if not articles:
        logger.warning("没有抓到任何文章，退出")
        sys.exit(0)

    total_raw = len(articles)

    # 2. 去重
    articles = deduplicate(articles)
    articles = cross_day_filter(articles)

    # 3. 按领域分组
    articles_by_cat: dict[str, list] = OrderedDict()
    for cat in VALID_CATEGORIES:
        if cat in sources:
            articles_by_cat[cat] = []

    for a in articles:
        if a.category in articles_by_cat:
            articles_by_cat[a.category].append(a)

    # "全球会议与重大活动" 额外从所有文章中关键词过滤
    if "全球会议与重大活动" in articles_by_cat:
        from .dedup import filter_by_category_events
        events = filter_by_category_events(articles)
        # 合并去重
        existing_urls = {a.url for a in articles_by_cat["全球会议与重大活动"]}
        for e in events:
            if e.url not in existing_urls:
                existing_urls.add(e.url)
                articles_by_cat["全球会议与重大活动"].append(e)

    total_after_dedup = sum(len(v) for v in articles_by_cat.values())
    total_sources = sum(len(src_list) for src_list in sources.values())

    # 4. 摘要
    digests = summarize_all(articles_by_cat)

    # 5. 生成日报
    report = DailyReport(
        date=report_date,
        generated_at=datetime.now(timezone.utc),
        model=cfg["api"]["model"],
        lookback_hours=cfg["fetch"]["lookback_hours"],
        total_sources=total_sources,
        total_articles=total_after_dedup,
        categories=digests,
    )

    # 6. 输出
    filepath = write_report(report, dry_run=args.dry_run)

    if not args.no_terminal:
        print_to_terminal(report)

    # 推送到微信
    if not args.dry_run:
        # PushPlus 推送（HTML 格式）
        html = render_news_html(report)
        push_to_pushplus(
            f"🧿 新闻之眼 · {report.date} 日报",
            html,
            template="html",
        )
        # 兼容旧 Server酱 推送
        push_to_wechat(report)
        logger.info(f"日报已保存: {filepath}")
    logger.info("完成")


def main_wechat() -> None:
    """微信公众号文章抓取模式"""
    import io
    import sys

    # Fix Windows GBK encoding for emoji output
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

    from .config import load_config, load_wechat_accounts
    from .logging_setup import setup_logging
    from .wechat_fetch import fetch_all_accounts
    from .wechat_report import (
        build_html_report, build_text_report, summarize_all_articles,
    )
    from .push import push_to_pushplus

    # 解析命令行参数
    parser = build_parser()
    args = parser.parse_args()

    cfg = load_config()
    log_level = "DEBUG" if args.verbose else cfg["logging"]["level"]
    setup_logging(level=log_level, log_file=cfg["logging"]["log_file"])
    logger.info("🔍 微信公众号抓取模式启动")

    # 加载配置
    wc_cfg = load_wechat_accounts()
    accounts = wc_cfg["accounts"]
    if not accounts:
        logger.warning("未配置任何公众号，请在 config/wechat_accounts.yaml 中添加")
        return
    if args.wechat_account:
        selected = [a.strip() for a in args.wechat_account.split(",")]
        accounts = [a for a in accounts if a in selected]
        if not accounts:
            logger.warning(f"指定的公众号不在配置中: {args.wechat_account}")
            return
        logger.info(f"限定公众号: {', '.join(accounts)}")

    logger.info(f"目标公众号 ({len(accounts)}): {', '.join(accounts)}")

    # 确定日期
    if args.date:
        report_date = args.date
    else:
        report_date = datetime.now(CHINA_TZ).strftime("%Y-%m-%d")

    # 1. 抓取文章
    articles_by_account = fetch_all_accounts(
        accounts,
        max_days=wc_cfg["max_days"],
        max_per_account=wc_cfg["max_per_account"],
        search_pages=wc_cfg["search_pages"],
        timeout=wc_cfg["timeout"],
    )

    total = sum(len(v) for v in articles_by_account.values())
    if total == 0:
        logger.warning("未抓取到任何文章")
        # 还是推送一条通知
        html = build_html_report(articles_by_account, report_date)
        if not args.dry_run:
            push_to_pushplus(
                f"📊 微信公众号日报 · {report_date}",
                html,
                template="html",
            )
        return

    # 2. AI 摘要
    if not args.dry_run:
        articles_by_account = summarize_all_articles(articles_by_account)

    # 3. 生成报告
    if not args.no_terminal:
        text = build_text_report(articles_by_account, report_date)
        print(text)

    # 4. 推送
    if not args.dry_run:
        html = build_html_report(articles_by_account, report_date)
        push_to_pushplus(
            f"📊 微信公众号日报 · {report_date}",
            html,
            template="html",
        )

    logger.info("微信抓取完成")


if __name__ == "__main__":
    main()
