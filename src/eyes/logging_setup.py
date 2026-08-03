"""日志设置"""

import logging
import sys
from pathlib import Path


def setup_logging(level: str = "INFO", log_file: str = "logs/run.log") -> None:
    """配置日志：同时输出到文件和终端"""
    from .config import PROJECT_ROOT

    log_path = PROJECT_ROOT / log_file
    log_path.parent.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger("eyes")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # 文件 handler
    fh = logging.FileHandler(str(log_path), encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # 终端 handler（仅 WARNING+）
    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(logging.WARNING)
    sh.setFormatter(fmt)
    root.addHandler(sh)
