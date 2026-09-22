"""
Hook script — runs on every UserPromptSubmit.
Checks for pending signals. If found, injects notification into Claude context.
Writes session->agent mapping for transcript_watcher.py.
Silent if no signals.
"""
import os, json, glob, sys, time, select

BASE = r"d:\ClothesNetData\chat-platform"
SIGNALS_DIR = os.path.join(BASE, "signals")

if not os.path.isdir(SIGNALS_DIR):
    exit(0)

signals = sorted(glob.glob(os.path.join(SIGNALS_DIR, "*.json")))
if not signals:
    exit(0)

# Try to read hook data for session_id (non-blocking — do NOT block!)
session_id = "unknown"
try:
    if select.select([sys.stdin], [], [], 0.1)[0]:
        raw = sys.stdin.read()
        if raw.strip():
            hook = json.loads(raw)
            session_id = hook.get("session_id", "unknown")
except Exception:
    pass

# Filter out old signals (>1 hour)
now = time.time()
active = []
agent_names_seen = []
for s in signals:
    try:
        with open(s, "r", encoding="utf-8") as f:
            data = json.load(f)
        if now - data.get("ts", 0) < 3600:
            basename = os.path.basename(s)
            active.append((basename, data))
            agent_name = basename.replace(".json", "")
            agent_names_seen.append(agent_name)
    except Exception:
        pass

if not active:
    exit(0)

# Write session->agent mapping for transcript_watcher
if session_id != "unknown" and agent_names_seen:
    mapping_file = os.path.join(SIGNALS_DIR, ".session_agent_map.json")
    try:
        existing = {}
        if os.path.exists(mapping_file):
            with open(mapping_file, "r", encoding="utf-8") as f:
                existing = json.load(f)
        existing[session_id] = agent_names_seen[0]
        with open(mapping_file, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False)
    except Exception:
        pass

# Mark signal files as injected
for name, data in active:
    sig_path = os.path.join(SIGNALS_DIR, name)
    injected_path = sig_path + ".injected"
    try:
        with open(injected_path, "w") as f:
            json.dump({"injected_at": now, "task_id": data.get("task_id", "?"),
                       "agent": name.replace(".json", "")}, f)
    except Exception:
        pass

# Output signal info -> injected into Claude context
agent_names = ", ".join(agent_names_seen) if agent_names_seen else "?"
print(f"<system-reminder>")
print(f"")
print(f"[A2A SIGNAL] Agents with pending tasks: {agent_names}")
for name, data in active:
    agent = name.replace(".json", "")
    print(f"")
    print(f"  Task for {agent}: {data.get('title', '?')[:100]}")
    print(f"  Task ID: {data.get('task_id', '?')}")
    desc = data.get("description", "")
    if desc:
        print(f"  Description: {desc[:500]}")
    print(f"  Action: claim and complete via A2A API")
print(f"")
print(f"</system-reminder>")
