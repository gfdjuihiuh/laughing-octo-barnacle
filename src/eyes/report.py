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


def render_news_html(report: DailyReport) -> str:
    """渲染 HTML 格式日报（适配 PushPlus 微信推送）"""
    lines = [
        '<!DOCTYPE html><html><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
        '<style>',
        'body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;padding:12px;font-size:14px;}',
        '.header{text-align:center;margin-bottom:16px;}',
        '.header h2{margin:0;font-size:18px;}',
        '.header p{color:#888;font-size:12px;margin:4px 0 0;}',
        '.cat{margin-bottom:14px;}',
        '.cat-title{font-size:15px;font-weight:bold;padding:6px 10px;',
        'background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;border-radius:6px 6px 0 0;}',
        '.cat-digest{padding:8px 10px;background:#f5f5f5;color:#666;font-size:12px;}',
        '.item{padding:8px 10px;border:1px solid #e0e0e0;border-top:none;}',
        '.item:last-of-type{border-radius:0 0 6px 6px;}',
        '.item-title{font-weight:bold;color:#333;margin-bottom:4px;}',
        '.item-summary{color:#555;font-size:13px;line-height:1.5;}',
        '.footer{text-align:center;font-size:11px;color:#bbb;margin-top:16px;',
        'padding-top:12px;border-top:1px solid #eee;}',
        '</style></head><body>',
        '<div class="header">',
        f'<h2>🧿 新闻之眼 · 每日简报</h2>',
        f'<p>{report.date} | {report.model} | {report.total_sources}源·{report.total_articles}条 | 过去{report.lookback_hours}h</p>',
        '</div>',
    ]

    for cat in report.categories:
        if not cat.items and not cat.error:
            continue
        lines.append('<div class="cat">')
        lines.append(f'<div class="cat-title">{cat.category}</div>')
        lines.append(f'<div class="cat-digest">{cat.digest}</div>')

        if cat.error:
            lines.append(f'<div class="item"><span style="color:red">⚠ {cat.error}</span></div>')

        for item in cat.items:
            title_html = item.title.replace("&", "&amp;").replace("<", "&lt;")
            summary_html = item.summary.replace("&", "&amp;").replace("<", "&lt;").replace("\n", "<br>")
            lines.append('<div class="item">')
            lines.append(f'<div class="item-title">{title_html}</div>')
            lines.append(f'<div class="item-summary">{summary_html}</div>')
            if item.link:
                lines.append(f'<div style="font-size:11px;margin-top:4px;">'
                           f'<a href="{item.link}" style="color:#667eea;">阅读原文</a> | 来源：{item.source}</div>')
            lines.append('</div>')

        lines.append('</div>')

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.append(f'<div class="footer">🧿 新闻之眼 · 自动生成于 {ts}</div>')
    lines.append('</body></html>')
    return "\n".join(lines)


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
