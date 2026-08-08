"""
新闻日报推送到企业微信机器人
用法: python send_to_wecom.py [report_path]
不传路径则自动取 reports/ 下最新的日报
"""
import json
import sys
import time
import uuid
import io
from pathlib import Path
import websocket

# Fix Windows GBK encoding for emoji output
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
except Exception:
    pass

# ============ 配置 ============
BOT_ID = "aib15jJENj1fIoMr7446GebUYp79dh4RQEs"
BOT_SECRET = "eBfTDWgmfRjxPo3nYgCdsQeRps3JGALCsUQOoSXJ59C"
RECEIVER = "WangQiEn"
WECOM_WS_URL = "wss://openws.work.weixin.qq.com"
GIT_DIR = Path(r"C:\Users\Blue\Desktop\git")
REPORTS_DIR = GIT_DIR / "reports"

RESULT = {"success": False, "error": ""}


def find_latest_report():
    """找到最新的新闻日报"""
    if not REPORTS_DIR.exists():
        return None
    reports = sorted(REPORTS_DIR.glob("新闻日报-*.md"), reverse=True)
    return reports[0] if reports else None


def read_report(path):
    """读取报告内容，限制长度（企微 markdown 消息有长度限制）"""
    content = Path(path).read_text(encoding="utf-8")
    max_len = 4000
    if len(content) > max_len:
        content = content[:max_len] + "\n\n...\n> ⚠️ 内容过长已截断，完整版请查看文件"
    return content


def send_message(ws, content):
    """发送 markdown 消息"""
    req_id = uuid.uuid4().hex[:16]
    ws.send(json.dumps({
        "cmd": "aibot_send_msg",
        "headers": {"req_id": req_id},
        "body": {
            "chatid": RECEIVER,
            "chat_type": 1,  # 1=单聊
            "msgtype": "markdown",
            "markdown": {"content": content},
        },
    }, ensure_ascii=False))
    print(f"  📤 已发送 (req_id={req_id})")


def on_open(ws):
    print("  🔗 WebSocket 已连接，发送订阅...")
    ws.send(json.dumps({
        "cmd": "aibot_subscribe",
        "headers": {"req_id": uuid.uuid4().hex[:16]},
        "body": {"bot_id": BOT_ID, "secret": BOT_SECRET},
    }, ensure_ascii=False))


def on_message(ws, raw):
    try:
        data = json.loads(raw) if isinstance(raw, str) else json.loads(raw.decode("utf-8"))
    except Exception:
        return

    cmd = data.get("cmd", "")
    headers = data.get("headers", {})
    body = data.get("body", {})

    if cmd == "subscribe":
        code = body.get("code", -1)
        if code == 0:
            print("  ✅ 订阅成功，发送日报...")
            # 发送消息
            content = RESULT.get("content", "")
            if content:
                send_message(ws, content)
            else:
                print("  ❌ 没有要发送的内容")
                ws.close()
        else:
            print(f"  ❌ 订阅失败: code={code}, msg={body.get('msg', '')}")
            RESULT["error"] = f"Subscribe failed: {body.get('msg', '')}"
            ws.close()
    elif cmd == "send_msg":
        code = body.get("code", -1)
        if code == 0:
            print("  ✅ 发送成功！")
            RESULT["success"] = True
        else:
            print(f"  ❌ 发送失败: code={code}, msg={body.get('msg', '')}")
            RESULT["error"] = f"Send failed: {body.get('msg', '')}"
        ws.close()
    else:
        # 忽略心跳等其他消息
        pass


def on_error(ws, error):
    print(f"  ❌ WebSocket 错误: {error}")
    RESULT["error"] = str(error)


def on_close(ws, status, msg):
    print(f"  🔌 WebSocket 已关闭 (status={status})")


def main():
    # 确定报告路径
    if len(sys.argv) > 1:
        report_path = Path(sys.argv[1])
    else:
        report_path = find_latest_report()

    if not report_path or not report_path.exists():
        print(f"❌ 找不到新闻日报文件")
        sys.exit(1)

    print(f"📰 读取日报: {report_path.name}")
    content = read_report(report_path)
    RESULT["content"] = content
    print(f"   ({len(content)} 字符)")

    print(f"🤖 连接企微机器人...")
    ws = websocket.WebSocketApp(
        WECOM_WS_URL,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )
    ws.run_forever()

    if RESULT["success"]:
        print("✅ 推送完成！")
        sys.exit(0)
    else:
        print(f"❌ 推送失败: {RESULT['error']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
