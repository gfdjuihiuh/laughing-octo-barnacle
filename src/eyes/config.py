"""配置加载与校验"""

import os
import yaml
from pathlib import Path
from typing import Any


# 项目根目录（git/）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"


# 有效的领域列表
VALID_CATEGORIES = ["科技", "金融", "文化", "民生", "军事", "政治", "全球会议与重大活动"]


class ConfigError(Exception):
    """配置错误"""
    pass


def _load_yaml(filename: str) -> dict[str, Any]:
    """加载 YAML 文件"""
    path = CONFIG_DIR / filename
    if not path.exists():
        raise ConfigError(f"配置文件不存在: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config() -> dict[str, Any]:
    """加载主配置，返回 dict"""
    return _load_yaml("config.yaml")


def load_sources() -> dict[str, list[dict]]:
    """加载新闻源配置，返回 {领域: [source_dict, ...]}"""
    raw = _load_yaml("sources.yaml")

    sources = {}
    for category in VALID_CATEGORIES:
        entries = raw.get(category, [])
        if not isinstance(entries, list):
            raise ConfigError(f"sources.yaml 中 '{category}' 应为列表")

        enabled = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if entry.get("enabled", True):
                enabled.append({
                    "name": entry["name"],
                    "url": entry["url"],
                    "lang": entry.get("lang", "zh"),
                    "category": category,
                })
        sources[category] = enabled

    total = sum(len(v) for v in sources.values())
    if total == 0:
        raise ConfigError("sources.yaml 中没有已启用的新闻源")
    return sources


def load_api_key() -> str:
    """从 .env 文件或环境变量加载 DEEPSEEK_API_KEY"""
    # 尝试 python-dotenv
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env")
    except ImportError:
        pass

    key = os.getenv("DEEPSEEK_API_KEY", "")
    if not key:
        # 也尝试从 .env 文件手动读取
        env_file = PROJECT_ROOT / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("DEEPSEEK_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break

    if not key or key == "sk-your-key-here":
        raise ConfigError(
            "未设置 DEEPSEEK_API_KEY。请在项目根目录创建 .env 文件，"
            "内容为: DEEPSEEK_API_KEY=你的密钥"
        )
    return key
