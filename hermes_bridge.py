"""
Hermes Bridge — connects the REAL Hermes (Nous Research) to A2A platform chat.
Polls A2A for messages mentioning "Hermes", forwards to Hermes CLI, posts reply back.
"""
import urllib.request, json, time, sys, os, subprocess, tempfile

BASE = os.path.dirname(os.path.abspath(__file__))
A2A = "http://localhost:8765"
HERMES_CLI = r"d:\Hermes\cli.py"
NAME = "Hermes"

last_seen_id = 0
lockfile = os.path.join(tempfile.gettempdir(), "hermes_bridge.lock")


def check_lock():
    """Prevent duplicate instances."""
    if os.path.exists(lockfile):
        try:
            with open(lockfile) as f:
                old_pid = int(f.read().strip())
            import ctypes
            SYNCHRONIZE = 0x100000
            handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, old_pid)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                print(f"[Bridge] Already running (PID {old_pid}). Exiting.")
                sys.exit(0)
        except Exception:
            os.remove(lockfile)
    with open(lockfile, "w") as f:
        f.write(str(os.getpid()))


SESSION_FILE = os.path.join(BASE, ".hermes_session_id")

def ask_hermes(question):
    """Ask the real Hermes. Uses --resume for persistent memory."""
    try:
        cmd = [sys.executable, HERMES_CLI]
        # Resume previous session if exists
        if os.path.exists(SESSION_FILE):
            with open(SESSION_FILE) as f:
                sid = f.read().strip()
            if sid:
                cmd += ["--resume", sid]
        cmd += ["-q", question]

        result = subprocess.run(
            cmd, cwd=r"d:\Hermes",
            capture_output=True, text=True, timeout=180,
            encoding="utf-8", errors="replace",
        )
        output = result.stdout.strip()

        # Extract session ID for next resume
        import re
        match = re.search(r'hermes --resume (\d{8}_\d{6}_\w{6})', output)
        if match:
            with open(SESSION_FILE, "w") as f:
                f.write(match.group(1))

        # Extract the REAL answer. Hermes CLI output has a lot of noise.
        if output:
            lines = output.split("\n")
            # Anything with box-drawing or TUI formatting is noise
            noise_chars = set("╭╰│╮╯├┤┌└▶●○─═╔╗╚╝║")
            skip_words = (
                "INFO", "Query:", "Initializing", "Session:", "Duration:",
                "Messages:", "Resume", "hermes --resume",
                "────────────────", "Query:",
            )
            meaningful = []
            for l in lines:
                s = l.strip()
                if not s or len(s) < 15:
                    continue
                # Skip noise
                if any(c in noise_chars for c in s):
                    continue
                if any(s.startswith(w) for w in skip_words):
                    continue
                if any(w in s for w in skip_words):
                    continue
                meaningful.append(s)
            if meaningful:
                # Take the longest meaningful lines — those are the actual response
                meaningful.sort(key=len, reverse=True)
                return "\n".join(meaningful[:15])
        return None
    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None


def post_reply(content):
    """Post Hermes' reply to A2A chat."""
    try:
        data = json.dumps({"sender": NAME, "content": content}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(f"{A2A}/api/send", data=data,
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


def main():
    global last_seen_id
    check_lock()

    # Start from latest message
    try:
        resp = urllib.request.urlopen(f"{A2A}/api/messages?since=0", timeout=5)
        msgs = json.loads(resp.read().decode())
        if isinstance(msgs, dict): msgs = msgs.get("messages", [])
        if msgs:
            last_seen_id = max(m.get("id", 0) for m in msgs if isinstance(m, dict))
    except Exception:
        pass

    print(f"[Hermes Bridge] Real Hermes connected. Starting from msg #{last_seen_id}.")

    pending = set()  # Track messages being processed

    while True:
        try:
            resp = urllib.request.urlopen(f"{A2A}/api/messages?since={time.time()-60}", timeout=5)
            msgs = json.loads(resp.read().decode())
            if isinstance(msgs, dict): msgs = msgs.get("messages", [])

            for m in msgs:
                if not isinstance(m, dict):
                    continue
                mid = m.get("id", 0)
                if mid <= last_seen_id or mid in pending:
                    continue
                last_seen_id = max(last_seen_id, mid)

                sender = m.get("sender", "")
                content = m.get("content", "")
                if sender in (NAME, "System") or NAME in sender:
                    continue

                content_lower = content.lower()
                if "hermes" in content_lower or "herme" in content_lower:
                    pending.add(mid)
                    print(f"[Bridge] {sender}: {content[:60]}...")
                    # Instant acknowledgement
                    post_reply(f"[Hermes] 收到「{content[:30]}...」，正在处理（预计30-60秒）...")
                    # Process (blocking - Hermes needs time to think)
                    answer = ask_hermes(content)
                    if answer:
                        post_reply(answer)
                        print(f"[Bridge] Replied ({len(answer)} chars)")
                    pending.discard(mid)
        except Exception:
            pass

        time.sleep(5)


if __name__ == "__main__":
    try:
        main()
    finally:
        try:
            os.remove(lockfile)
        except Exception:
            pass
