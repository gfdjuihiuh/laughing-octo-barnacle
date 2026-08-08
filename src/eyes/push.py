"""推送模块 — 通过 PushPlus / Server酱 推送到微信"""

import logging
import os
from email.mime.text import MIMEText

import requests

from .config import load_config

logger = logging.getLogger("eyes.push")

SERVERCHAN_URL = "https://sctapi.ftqq.com"
PUSHPLUS_URL = "https://www.pushplus.plus/send"


# ============================================================
# 通用新闻日报推送（Server酱）
# ============================================================

def push_to_wechat(report) -> bool:
    """通过 Server酱 将日报摘要推送到微信"""
    cfg = load_config()
    sendkey = cfg.get("push", {}).get("serverchan_key", "")
    if not sendkey:
        logger.debug("未配置 Server酱 SendKey，跳过推送")
        return False

    # 构建推送内容
    title = f"🧿 新闻之眼 · {report.date} 日报"

    lines = [
        f"## 新闻之眼 · {report.date} 日报",
        f"",
        f"> 模型：{report.model} | {report.total_sources}个源 · {report.total_articles}条新闻",
        f"",
    ]
    for cat in report.categories:
        if cat.items:
            lines.append(f"### {cat.category}")
            lines.append(f"> {cat.digest}")
            lines.append("")
            for item in cat.items[:3]:
                lines.append(f"- **{item.title}** — _{item.source}_")
            lines.append("")

    content = "\n".join(lines)

    try:
        resp = requests.post(
            f"{SERVERCHAN_URL}/{sendkey}.send",
            data={"title": title, "desp": content},
            timeout=10,
        )
        data = resp.json()
        if data.get("code") == 0:
            logger.info("✓ 微信推送成功 (Server酱)")
            return True
        else:
            logger.warning(f"微信推送失败: {data.get('message', resp.text)}")
            return False
    except Exception as e:
        logger.warning(f"微信推送异常: {e}")
        return False


# ============================================================
# 微信公众号文章推送（PushPlus）
# ============================================================

def _load_pushplus_token() -> str:
    """从多处加载 PushPlus Token（优先级：环境变量 > .env 文件 > config）"""
    # 1. 环境变量（GitHub Actions secrets）
    token = os.getenv("PUSHPLUS_TOKEN", "")
    if token:
        return token

    # 2. .env 文件
    try:
        from pathlib import Path
        env_file = Path(__file__).resolve().parent.parent.parent / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("PUSHPLUS_TOKEN="):
                    token = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if token:
                        return token
    except Exception:
        pass

    # 3. wechat_accounts.yaml 配置
    try:
        from .config import _load_yaml
        wc_cfg = _load_yaml("wechat_accounts.yaml")
        token = wc_cfg.get("wechat", {}).get("push", {}).get("pushplus_token", "")
    except Exception:
        pass

    return token


def push_to_pushplus(title: str, content: str, template: str = "html") -> bool:
    """通过 PushPlus 推送消息到微信

    Args:
        title: 消息标题
        content: 消息正文（支持 HTML）
        template: 消息模板 (html / markdown / txt / json)

    Returns:
        是否推送成功
    """
    token = _load_pushplus_token()
    if not token:
        logger.debug("未配置 PushPlus Token，跳过推送")
        return False

    try:
        resp = requests.post(
            "https://www.pushplus.plus/send",
            json={
                "token": token,
                "title": title,
                "content": content,
                "template": template,
            },
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        data = resp.json()
        code = data.get("code")
        if code == 200:
            logger.info("✓ PushPlus 推送成功")
            return True
        else:
            logger.warning(f"PushPlus 推送失败: code={code}, msg={data.get('msg', resp.text)}")
            return False
    except Exception as e:
        logger.warning(f"PushPlus 推送异常: {e}")
        return False
