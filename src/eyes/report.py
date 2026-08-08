"""报告输出模块 — Markdown 日报 + 终端输出"""

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

from .config import PROJECT_ROOT, load_config
from .models import DailyReport, CategoryDigest

logger = logging.getLogger("eyes.report")


def render_markdown(report: DailyReport) -> str:
    """渲染 Markdown 日报字符串"""
    lines = [
        f"# 🧿 新闻之眼 · 每日简报",
        f"",
        f"**日期**：{report.date}  |  **模型**：{report.model}  |  "
        f"**时间窗口**：过去 {report.lookback_hours} 小时  |  "
        f"**来源**：{report.total_sources} 个源 · {report.total_articles} 条文章",
        f"",
        f"---",
        f"",
    ]

    # 各领域详细
    for cat in report.categories:
        lines.append(f"## {cat.category}")
        lines.append("")
        lines.append(f"> {cat.digest}")
        lines.append("")

        if cat.error:
            lines.append(f"⚠️ *摘要生成异常：{cat.error}*")
            lines.append("")

        if not cat.items:
            lines.append("_今日无重要更新_")
            lines.append("")
            continue

        for i, item in enumerate(cat.items, 1):
            lines.append(f"### {i}. {item.title}")
            lines.append("")
            lines.append(f"{item.summary}")
            lines.append("")

        lines.append("")

    lines.append("---")
    lines.append(f"*由 [新闻之眼] 自动生成于 {report.generated_at.strftime('%Y-%m-%d %H:%M UTC')}*")

    return "\n".join(lines)


def write_report(report: DailyReport, dry_run: bool = False) -> str:
    """写入日报文件，返回主文件路径。dry_run 时仅返回内容不写文件。"""
    cfg = load_config()
    reports_dir = PROJECT_ROOT / cfg["output"]["reports_dir"]
    reports_dir.mkdir(parents=True, exist_ok=True)

    content = render_markdown(report)
    filename = f"新闻日报-{report.date}.md"
    filepath = reports_dir / filename

    if dry_run:
        return content

    # 原子写入主目录
    _atomic_write(content, reports_dir, filename)

    # 额外输出目录（如桌面）
    extra_dir = cfg["output"].get("extra_output_dir", "")
    if extra_dir:
        extra_path = Path(extra_dir)
        extra_path.mkdir(parents=True, exist_ok=True)
        _atomic_write(content, extra_path, filename)
        logger.info(f"日报已同步到: {extra_path / filename}")

    logger.info(f"日报已写入: {filepath}")
    return str(filepath)


def _atomic_write(content: str, directory: Path, filename: str) -> None:
    """写入文件：先写临时文件再 rename，失败则直接写入"""
    import time
    target = directory / filename
    tmp = NamedTemporaryFile(mode="w", suffix=".md", delete=False,
                             encoding="utf-8", dir=str(directory))
    tmp_path = tmp.name
    try:
        tmp.write(content)
        tmp.flush()
        try:
            os.replace(tmp_path, str(target))
        except (PermissionError, OSError):
            # Windows 锁文件问题：直接写入目标文件
            target.write_text(content, encoding="utf-8")
    finally:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def print_to_terminal(report: DailyReport) -> None:
    """终端彩色输出精简版"""
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.text import Text

        console = Console()

        title = Text("🧿 新闻之眼 · 每日简报", style="bold cyan")
        meta = Text(
            f"{report.date} | {report.model} | {report.total_sources}源·"
            f"{report.total_articles}条 | 过去{report.lookback_hours}h",
            style="dim",
        )
        console.print(Panel(title + Text("\n") + meta))

        for cat in report.categories:
            console.print(f"\n[bold yellow]▍{cat.category}[/bold yellow]  [dim]{cat.digest}[/dim]")

            if cat.error:
                console.print(f"  [red]⚠ {cat.error}[/red]")

            for i, item in enumerate(cat.items[:5], 1):
                console.print(f"  {i}. [bold]{item.title}[/bold]")
                console.print(f"     {item.summary[:120]}{'...' if len(item.summary) > 120 else ''}")

        console.print(f"\n[dim]─── 完整报告见 reports/{report.date}.md ───[/dim]")

    except ImportError:
        # 无 rich 库时的兜底输出
        print(f"\n{'='*60}")
        print(f"  新闻之眼 · 每日简报  |  {report.date}")
        print(f"{'='*60}")
        for cat in report.categories:
            print(f"\n▍{cat.category} — {cat.digest}")
            for i, item in enumerate(cat.items[:5], 1):
                print(f"  {i}. {item.title}")
                print(f"     {item.summary[:120]}")
        print(f"\n--- 完整报告见 reports/{report.date}.md ---")
