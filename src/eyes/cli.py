"""命令行入口 — argparse 参数解析"""

import argparse
import sys
from datetime import datetime, timezone

from .config import VALID_CATEGORIES
from .logging_setup import setup_logging


def build_parser() -> argparse.ArgumentParser:
    """构建参数解析器"""
    parser = argparse.ArgumentParser(
        prog="eyes",
        description="🧿 新闻之眼 — 全领域新闻聚合摘要系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python -m eyes                   # 正常运行
  python -m eyes --dry-run         # 终端预览，不写文件
  python -m eyes --check-sources   # 检查所有 RSS 源可用性
  python -m eyes --date 2026-08-02 # 回溯生成指定日期日报
  python -m eyes --category 科技,金融  # 仅处理指定领域
        """,
    )

    parser.add_argument(
        "--dry-run", action="store_true",
        help="终端预览日报，不写入 reports/ 目录",
    )
    parser.add_argument(
        "--check-sources", action="store_true",
        help="逐个检查所有 RSS 新闻源的可达性",
    )
    parser.add_argument(
        "--date", type=str, default=None,
        help="指定日期 (YYYY-MM-DD 格式)，默认今天",
    )
    parser.add_argument(
        "--category", type=str, default=None,
        help=f"仅处理指定领域，逗号分隔。可选: {', '.join(VALID_CATEGORIES)}",
    )
    parser.add_argument(
        "--no-terminal", action="store_true",
        help="不在终端输出日报摘要",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="详细日志输出",
    )
    parser.add_argument(
        "--wechat", action="store_true",
        help="微信公众号文章抓取模式（抓取 + AI 摘要 + 推送）",
    )
    parser.add_argument(
        "--wechat-account", type=str, default=None,
        help="仅抓取指定公众号，逗号分隔（不传则抓取全部已配置账号）",
    )

    return parser


def parse_categories(category_arg: str | None) -> list[str] | None:
    """解析 --category 参数"""
    if category_arg is None:
        return None
    cats = [c.strip() for c in category_arg.split(",")]
    for c in cats:
        if c not in VALID_CATEGORIES:
            print(f"错误：无效领域 '{c}'。可选: {', '.join(VALID_CATEGORIES)}", file=sys.stderr)
            sys.exit(1)
    return cats
