"""python -m eyes 入口"""

import logging
import sys
from collections import OrderedDict
from datetime import datetime, timezone

from .cli import build_parser, parse_categories
from .config import VALID_CATEGORIES, load_config, load_sources
from .fetch import check_sources, fetch_all
from .dedup import cross_day_filter, deduplicate, filter_by_category_events
from .logging_setup import setup_logging
from .models import DailyReport
from .report import print_to_terminal, write_report
from .summarize import summarize_all

logger = logging.getLogger("eyes")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

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
        report_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

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

    if not args.dry_run:
        logger.info(f"日报已保存: {filepath}")
    logger.info("完成")


if __name__ == "__main__":
    main()
