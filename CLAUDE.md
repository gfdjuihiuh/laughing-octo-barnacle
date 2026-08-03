# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**🧿 新闻之眼 (eyes)** — 全领域新闻聚合摘要系统。每日自动抓取 7 大领域新闻（科技/金融/文化/民生/军事/政治/全球会议），通过 DeepSeek API 生成中文日报。

## Project Structure

```
config/          # YAML 配置（主配置 + 新闻源注册表）
src/eyes/        # 核心 Python 包
  __main__.py    # python -m eyes 入口
  cli.py         # 命令行参数
  config.py      # 配置加载
  models.py      # 数据模型
  fetch.py       # RSS 并发抓取
  dedup.py       # URL/标题去重
  summarize.py   # DeepSeek API 摘要
  report.py      # Markdown + 终端输出
reports/         # 日报输出（gitignore）
scripts/         # 调度脚本
config/          # YAML 配置文件
```

## Key Commands

```bash
python -m eyes                    # 正常运行
python -m eyes --dry-run          # 终端预览，不写文件
python -m eyes --check-sources    # 检查 RSS 源可用性
python -m eyes --date 2026-08-02  # 回溯生成
python -m eyes --category 科技,金融  # 指定领域
python -m eyes -v                 # 详细日志
```

## Environment

- Python 3.12 in `.venv/`
- DeepSeek API key in `.env` (not committed)
- Windows 10, schedules via `schtasks` (see `scripts/install_schedule.ps1`)

## Custom Commands

This project has 12 custom slash commands defined in `.claude/commands/`:

| Command | Purpose |
|---------|---------|
| `/commit` | Analyze changes and create commit messages |
| `/debug` | Find and fix bugs |
| `/explain` | Explain code in an easy-to-understand way |
| `/lint` | Automatically check and fix code style |
| `/optimize` | Find and fix performance issues |
| `/pr` | Generate PR descriptions for the current branch |
| `/refactor` | Make code cleaner and more maintainable |
| `/review` | Review code and provide practical feedback |
| `/security` | Find and report security vulnerabilities |
| `/ship` | Run essential checks before deployment |
| `/test` | Write practical and executable tests |

## Git Notes

- `.gitignore` excludes `.claude/`, `.env`, `.venv/`, `logs/`, `state/`, `reports/`, OS files, IDE directories.
