"""
Hermes — A2A Platform Orchestrator. Single process.
- Real-time chat with memory
- Database access (agents, tasks)
- Capability matching
- Task creation and assignment

Run: python hermes_chat.py
Just ONE instance. No duplicates.
"""
import urllib.request, json, time, sys, os

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import db

A2A = "http://localhost:8765"
NAME = "Hermes"
AGENT_ID = "Hermes-f45b88"

last_seen_id = 0
chat_history = []


def init_last_id():
    """Jump to latest message so we don't reply to history."""
    global last_seen_id
    try:
        msgs = db.message_all(time.time() - 3600)
        if msgs:
            last_seen_id = max(m.get("id", 0) for m in msgs)
    except Exception:
        pass


def get_new_messages():
    """Get only messages newer than last_seen_id."""
    global last_seen_id
    try:
        since_ts = time.time() - 300
        msgs = db.message_all(since_ts)
        new = [m for m in msgs if isinstance(m, dict) and m.get("id", 0) > last_seen_id]
        return new
    except Exception:
        return []


def reply(content):
    """Post a chat message as Hermes."""
    try:
        data = json.dumps({"sender": NAME, "content": content}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(f"{A2A}/api/send", data=data,
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


def platform_summary():
    """Get current platform status."""
    try:
        agents = db.agent_all()
        tasks = db.task_all()
        online = sum(1 for a in agents if a.get("status") != "offline")
        pending = sum(1 for t in tasks if t.get("status") == "pending")
        agent_names = [a["name"] for a in agents if a.get("status") != "offline"]
        return f"Platform: {online}/{len(agents)} agents online ({', '.join(agent_names)}). {pending} tasks pending."
    except Exception:
        return "Platform status unavailable."


def think(user_msg):
    """Real AI response with platform context and memory."""
    global chat_history
    try:
        from ai_config import get_config
        cfg = get_config()
        url = cfg["base_url"].rstrip("/") + "/v1/chat/completions"
        model = cfg["model"].split("/")[-1] if "/" in cfg["model"] else cfg["model"]

        status = platform_summary()
        system_prompt = f"""You are Hermes, the A2A multi-agent platform orchestrator.

Current platform state: {status}

You manage these agents:
- Claude: general worker (code, reasoning, tasks)
- QualityEvaluator: quality inspector (8-dim detection: E401/E501/E502/E503/E510/W601/STUCK/THIN)
- BPTtrain: training operations
- BPT_Data_Check: data validation
- Hermes (yourself): orchestrator

Your capabilities: task creation and assignment via capability matching, platform monitoring, agent coordination.
The platform uses OS-level wake-up (Win32 API + pyautogui) to activate VS Code windows when tasks arrive.
Desktop watcher checks signals/ every 2 seconds for new tasks.

Be conversational, helpful, and concise. Speak Chinese to Chinese-speaking users."""

        messages = [{"role": "system", "content": system_prompt}]
        messages += chat_history[-20:]  # Last 10 exchanges
        messages.append({"role": "user", "content": user_msg})

        body = json.dumps({
            "model": model,
            "messages": messages,
            "max_tokens": 400, "temperature": 0.7,
        }).encode()

        req = urllib.request.Request(url, data=body, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg['api_key']}",
        })
        resp = urllib.request.urlopen(req, timeout=30)
        data = json.loads(resp.read().decode())
        answer = data["choices"][0]["message"]["content"].strip()

        # Remember conversation
        chat_history.append({"role": "user", "content": user_msg})
        chat_history.append({"role": "assistant", "content": answer})
        if len(chat_history) > 40:
            chat_history = chat_history[-40:]

        return answer
    except Exception as e:
        return None  # Don't reply if AI fails


def main():
    global last_seen_id

    # PID lock — prevent duplicate instances
    import tempfile
    lockfile = os.path.join(tempfile.gettempdir(), "hermes_chat.lock")
    if os.path.exists(lockfile):
        try:
            with open(lockfile) as f:
                old_pid = int(f.read().strip())
            # Check if old process is still alive
            import ctypes
            SYNCHRONIZE = 0x100000
            handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, old_pid)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                print(f"[Hermes] Already running (PID {old_pid}). Exiting.")
                sys.exit(0)
        except Exception:
            os.remove(lockfile)

    with open(lockfile, "w") as f:
        f.write(str(os.getpid()))

    init_last_id()
    print(f"[Hermes] Platform Orchestrator. Starting from msg #{last_seen_id}.")
    print(f"[Hermes] {platform_summary()}")
    print(f"[Hermes] Listening for chat (say 'Hermes' to talk)...")

    while True:
        try:
            msgs = get_new_messages()
            for m in msgs:
                last_seen_id = max(last_seen_id, m.get("id", 0))

                sender = m.get("sender", "")
                content = m.get("content", "")

                if sender in (NAME, "System") or NAME in sender:
                    continue

                content_lower = content.lower()
                if "hermes" in content_lower or "herme" in content_lower:
                    print(f"[Hermes] {sender}: {content[:60]}...")
                    answer = think(content)
                    if answer:
                        reply(answer)
                        print(f"[Hermes] Replied ({len(answer)} chars)")
        except Exception:
            pass

        time.sleep(3)


if __name__ == "__main__":
    try:
        main()
    finally:
        try:
            os.remove(os.path.join(__import__('tempfile').gettempdir(), "hermes_chat.lock"))
        except Exception:
            pass
