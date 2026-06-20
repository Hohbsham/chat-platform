"""
A2A Auto-Responder — background service that processes WeCom requests.
Runs alongside Hermes. Monitors A2A chat for commands, executes them, posts results.

Usage: python a2a_service.py
"""
import time, json, os, sys, urllib.request

HOST = "http://localhost:8765"
BASE = os.path.dirname(os.path.abspath(__file__))

def get(path):
    return json.loads(urllib.request.urlopen(f"{HOST}{path}", timeout=10).read())

def post(path, data):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(f"{HOST}{path}", data=body,
        headers={"Content-Type": "application/json; charset=utf-8"})
    return json.loads(urllib.request.urlopen(req, timeout=10).read())

def run_cli(args):
    """Run a2a_cli.py and return output."""
    import subprocess
    result = subprocess.run(
        ["python", os.path.join(BASE, "a2a_cli.py")] + args,
        capture_output=True, text=True, timeout=15, cwd=BASE
    )
    return result.stdout or result.stderr

def handle_command(sender, content):
    """Parse user message and execute A2A commands."""
    content_lower = content.lower().strip()

    # Check agents
    if any(w in content_lower for w in ["查", "看", "有哪些", "列出"]) and any(w in content_lower for w in ["专家", "agent", "在线", "团队"]):
        output = run_cli(["agents"])
        post("/api/send", {"sender": "A2A-Service", "content": f"当前在线专家：\n\n```\n{output.strip()}\n```"})
        return True

    # Clean up
    if any(w in content_lower for w in ["清理", "清除", "删"]) and any(w in content_lower for w in ["重复", "僵尸", "bridge"]):
        output = run_cli(["cleanup"])
        post("/api/send", {"sender": "A2A-Service", "content": f"清理完成：\n\n```\n{output.strip()}\n```"})
        return True

    # Check tasks
    if any(w in content_lower for w in ["任务", "task", "进度"]):
        output = run_cli(["tasks", "--all"])
        post("/api/send", {"sender": "A2A-Service", "content": f"任务列表：\n\n```\n{output.strip()}\n```"})
        return True

    return False

def main():
    print("[A2A Service] Starting...")
    print(f"[A2A Service] Monitoring {HOST}")

    # Register
    agent_id = f"A2A-Service-{__import__('uuid').uuid4().hex[:6]}"
    post("/api/agents/register", {
        "agent_id": agent_id, "name": "A2A-Service",
        "role": "A2A Command Auto-Responder",
        "goal": "Execute A2A management commands and report results",
        "backstory": "Background service that handles A2A platform operations.",
        "capabilities": ["chat", "agent_management"],
    })
    print(f"[A2A Service] Registered: {agent_id}")

    last_ts = time.time()
    processed_ids = set()

    while True:
        try:
            post("/api/agents/heartbeat", {"agent_id": agent_id})

            msgs = get(f"/api/messages?since={last_ts}")
            for m in msgs:
                last_ts = max(last_ts, m.get("ts", 0))
                msg_id = f"{m.get('ts')}:{m.get('sender')}"
                if msg_id in processed_ids:
                    continue
                processed_ids.add(msg_id)
                # Keep set small
                if len(processed_ids) > 100:
                    processed_ids.clear()

                mtype = m.get("type", "")
                sender = m.get("sender", "")
                content = m.get("content", "")

                # Only process chat messages from WeCom users
                if mtype != "chat":
                    continue
                if "A2A-Service" in sender or "Hermes" in sender:
                    continue
                if "(WX)" not in sender:
                    # Try to handle anyway if it looks like a command
                    pass

                handled = handle_command(sender, content)
                if handled:
                    print(f"[A2A Service] Handled: {sender[:30]}: {content[:60]}")

        except Exception as e:
            print(f"[A2A Service] Error: {e}")

        time.sleep(2)

if __name__ == "__main__":
    main()
