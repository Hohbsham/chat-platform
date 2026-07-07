"""
Hook script — runs on every UserPromptSubmit.
Checks for pending signals. If found, injects notification into Claude context.
Silent if no signals.
"""
import os, json, glob

BASE = r"d:\ClothesNetData\chat-platform"
SIGNALS_DIR = os.path.join(BASE, "signals")

if not os.path.isdir(SIGNALS_DIR):
    exit(0)

signals = sorted(glob.glob(os.path.join(SIGNALS_DIR, "*.json")))
if not signals:
    exit(0)

# Filter out old signals (>1 hour)
import time
now = time.time()
active = []
for s in signals:
    try:
        with open(s, "r", encoding="utf-8") as f:
            data = json.load(f)
        if now - data.get("ts", 0) < 3600:
            active.append((os.path.basename(s), data))
    except Exception:
        pass

# Also check wake file from VSCode Extension
wake_file = os.path.join(BASE, "signals", ".wake_now.txt")
if os.path.exists(wake_file):
    with open(wake_file, "r", encoding="utf-8") as f:
        wake_content = f.read().strip()
    if wake_content:
        active.append((".wake_now.txt", {"title": wake_content[:80], "task_id": "see-context/latest_task.md", "ts": time.time()}))
    os.remove(wake_file)  # Consume the wake signal

if not active:
    exit(0)

# Delete consumed signal files — task is now in Claude's context
for name, data in active:
    if name == ".wake_now.txt":
        continue
    sig_path = os.path.join(SIGNALS_DIR, name)
    try:
        os.remove(sig_path)
    except Exception:
        pass

# Output signal info → injected into Claude context
print("<system-reminder>")
print("")
for name, data in active:
    agent = name.replace(".json", "")
    print(f"[A2A SIGNAL] {agent}: {data.get('title', '?')[:80]}")
    print(f"  Task ID: {data.get('task_id', '?')}")
    print(f"  Age: {int(now - data.get('ts', 0))}s ago")
    print(f"  Action: claim and complete this task")
    print()
print("</system-reminder>")
