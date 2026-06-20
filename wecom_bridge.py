"""
WeCom (企业微信) Notification Bridge
Push agent task results to WeChat via WeCom group bot webhook.

Setup:
  1. Create a WeCom group (企业微信群)
  2. Add a group bot (群机器人) → get webhook URL
  3. Set WECOM_WEBHOOK env or paste in config

Usage:
  python wecom_bridge.py --webhook "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx"
  # Or via env: WECOM_WEBHOOK_URL
"""
import json, os, sys, urllib.request

WEBHOOK = os.environ.get("WECOM_WEBHOOK_URL", "")

def send_markdown(title, content):
    """Send markdown message to WeCom group."""
    if not WEBHOOK:
        return False, "WECOM_WEBHOOK_URL not set"

    body = json.dumps({
        "msgtype": "markdown",
        "markdown": {
            "content": f"## {title}\n{content}\n<font color=\"comment\">A2A Agent Platform</font>"
        }
    }).encode("utf-8")

    try:
        req = urllib.request.Request(WEBHOOK, data=body,
            headers={"Content-Type": "application/json"})
        resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
        return resp.get("errcode") == 0, resp.get("errmsg", "ok")
    except Exception as e:
        return False, str(e)

def send_text(text):
    """Send plain text to WeCom group."""
    if not WEBHOOK:
        return False, "WECOM_WEBHOOK_URL not set"

    body = json.dumps({"msgtype": "text", "text": {"content": text}}).encode("utf-8")
    try:
        req = urllib.request.Request(WEBHOOK, data=body,
            headers={"Content-Type": "application/json"})
        resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
        return resp.get("errcode") == 0, resp.get("errmsg", "ok")
    except Exception as e:
        return False, str(e)

def notify_task_complete(agent_name, agent_role, task_title, result_summary):
    """Send a task completion notification."""
    title = f"✅ Agent 完成: {task_title}"
    # Truncate long results
    result = result_summary[:500] + ("..." if len(result_summary) > 500 else "")
    content = (
        f"**Agent**: {agent_name}\n"
        f"**角色**: {agent_role}\n"
        f"**任务**: {task_title}\n\n"
        f"**结果**:\n{result}"
    )
    return send_markdown(title, content)

def notify_task_claimed(agent_name, task_title):
    """Notify that an agent claimed a task."""
    return send_text(f"🔔 {agent_name} 领取了任务「{task_title}」")

# ── CLI ──
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="WeCom Bridge")
    p.add_argument("--webhook", help="WeCom bot webhook URL")
    p.add_argument("--test", action="store_true", help="Send test message")
    args = p.parse_args()

    if args.webhook:
        WEBHOOK = args.webhook

    if args.test:
        ok, msg = send_markdown("🧪 测试通知",
            "A2A Agent Platform 通知桥已连通\n请查收此消息以确认配置正确")
        print(f"Test: {'OK' if ok else 'FAILED'} — {msg}")
    else:
        print(f"Webhook: {'Configured' if WEBHOOK else 'NOT SET'}")
        print("Usage: python wecom_bridge.py --webhook <URL> --test")
