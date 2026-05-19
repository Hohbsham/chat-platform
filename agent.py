"""
A2A Agent client. Usage:

  # Registration
  python agent.py register --name Claude --capabilities code_review,file_edit

  # Auto mode (register + poll + claim + execute)
  python agent.py auto --name Claude --capabilities code_review,file_edit [--poll-interval 5]

  # Task operations
  python agent.py create-task --title "Review server.py" --desc "Check for bugs" --capabilities code_review --creator Claude
  python agent.py tasks [--status pending]
  python agent.py claim --task-id task-xxx
  python agent.py complete --task-id task-xxx --result "No issues found"
  python agent.py fail --task-id task-xxx --error "Cannot access file"
  python agent.py heartbeat

  # Chat (original commands)
  python agent.py send --name Claude --msg "Hello everyone!"
  python agent.py read [--since <ts>]
  python agent.py listen
"""
import json, time, sys, os, uuid, urllib.request, urllib.error

# Fix Windows GBK encoding for emoji
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = os.path.dirname(__file__)
AGENT_ID_FILE = os.path.join(BASE_DIR, ".agent_id")
HOST = os.environ.get("CHAT_HOST", "http://localhost:8765")

# ── HTTP helpers ────────────────────────────────────────────────

def api_get(path):
    url = f"{HOST}{path}"
    resp = urllib.request.urlopen(url)
    return json.loads(resp.read().decode("utf-8"))

def api_post(path, data):
    url = f"{HOST}{path}"
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=body,
        headers={"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req)
        return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode("utf-8"))

# ── Identity ────────────────────────────────────────────────────

def load_agent_id():
    if os.path.exists(AGENT_ID_FILE):
        with open(AGENT_ID_FILE, "r") as f:
            return f.read().strip()
    return None

def save_agent_id(agent_id):
    with open(AGENT_ID_FILE, "w") as f:
        f.write(agent_id)

def get_or_create_agent_id(name):
    """Stable identity: load existing or create new. Returns agent_id."""
    existing = load_agent_id()
    if existing:
        parts = existing.rsplit("-", 1)
        if parts[0] == name:
            return existing
    agent_id = f"{name}-{uuid.uuid4().hex[:6]}"
    save_agent_id(agent_id)
    return agent_id

# ── Commands ────────────────────────────────────────────────────

def cmd_register(args):
    agent_id = get_or_create_agent_id(args.name)
    caps = _parse_caps(args.capabilities)
    result = api_post("/api/agents/register", {
        "agent_id": agent_id,
        "name": args.name,
        "capabilities": caps
    })
    print(f"[REGISTERED] {args.name} ({agent_id})")
    print(f"  Capabilities: {', '.join(caps) if caps else 'none'}")
    return agent_id

def cmd_heartbeat(args):
    agent_id = args.agent_id or load_agent_id()
    if not agent_id:
        print("[ERROR] No agent_id. Run register first or pass --agent-id.")
        sys.exit(1)
    result = api_post("/api/agents/heartbeat", {"agent_id": agent_id})
    print(f"[HEARTBEAT] {agent_id} — {'ok' if result.get('ok') else 'error'}")

def cmd_auto(args):
    agent_id = get_or_create_agent_id(args.name)
    caps = _parse_caps(args.capabilities)
    interval = int(args.poll_interval) if args.poll_interval else 5
    verbose = args.verbose
    once = args.once
    tick = 0

    # Register
    api_post("/api/agents/register", {
        "agent_id": agent_id,
        "name": args.name,
        "capabilities": caps
    })
    safe_print(f"[REGISTERED] {args.name} ({agent_id}) with: {', '.join(caps) if caps else 'none'}")
    if once:
        safe_print(f"[AUTO] Checking once for matching tasks...")
    else:
        safe_print(f"[AUTO] Polling every {interval}s. Ctrl+C to stop.\n")

    running = True
    while running:
        try:
            # Heartbeat
            api_post("/api/agents/heartbeat", {"agent_id": agent_id})
            tick += 1
            # Auto-claim
            result = api_post("/api/tasks/auto-claim", {
                "agent_id": agent_id,
                "capabilities": caps
            })
            if result.get("error"):
                safe_print(f"[AUTO] Error: {result['error']}")
            elif result.get("claimed"):
                task = result["claimed"]
                safe_print(f"[AUTO] Claimed {task['task_id']}: \"{task['title']}\"")
                safe_print(f"       Creator: {task['creator']}  |  Priority: {task['priority']}")
                safe_print(f"       Required: {', '.join(task['required_capabilities'])}")
                if task.get("description"):
                    safe_print(f"       Description: {task['description']}")
                # Prompt for result
                safe_print(f"\n  Enter result (multi-line, /done to finish, Ctrl+C to skip):")
                try:
                    lines = []
                    while True:
                        line = input()
                        if line.strip().lower() == "/done":
                            break
                        lines.append(line)
                    result_text = "\n".join(lines) if lines else f"Task handled by {args.name}."
                except (KeyboardInterrupt, EOFError):
                    safe_print("  (skipped)")
                    result_text = f"Task acknowledged by {args.name}."
                api_post(f"/api/tasks/{task['task_id']}/complete", {
                    "agent_id": agent_id,
                    "result": result_text
                })
                safe_print(f"[COMPLETED] {task['task_id']}: {task['title']}\n")
                if once:
                    running = False
            else:
                if verbose:
                    t = time.strftime("%H:%M:%S")
                    pending = _count_pending_tasks()
                    matching = _count_matching_tasks(caps)
                    safe_print(f"[AUTO] {t} tick#{tick} heartbeat ok, {pending} pending, {matching} matching")
                if once:
                    safe_print("[AUTO] No matching tasks. Exiting.")
                    running = False
        except urllib.error.URLError as e:
            safe_print(f"[AUTO] Connection error: {e}")
        except KeyboardInterrupt:
            running = False
        except Exception as e:
            safe_print(f"[AUTO] Unexpected error: {e}")

        if running and not once:
            try:
                time.sleep(interval)
            except KeyboardInterrupt:
                running = False

    # Graceful shutdown
    if not once:
        try:
            api_post("/api/agents/unregister", {"agent_id": agent_id})
            safe_print("[OFFLINE] Unregistered.")
        except Exception:
            pass
        safe_print("Bye.")
    print("Bye.")

def cmd_create_task(args):
    caps = _parse_caps(args.capabilities) if args.capabilities else []
    result = api_post("/api/tasks", {
        "title": args.title,
        "description": args.desc or "",
        "required_capabilities": caps,
        "priority": args.priority or "normal",
        "creator": args.creator or "Anonymous"
    })
    if result.get("ok"):
        task = result["task"]
        print(f"[CREATED] {task['task_id']}: \"{task['title']}\"")
        print(f"  Status: {task['status']}, Priority: {task['priority']}")
        print(f"  Requires: {', '.join(caps) if caps else 'none'}")
    else:
        print(f"[ERROR] {result.get('error', 'Unknown error')}")

def cmd_tasks(args):
    status = args.status or ""
    path = f"/api/tasks{'?status=' + status if status else ''}"
    tasks = api_get(path)
    if isinstance(tasks, dict):
        tasks = [tasks]
    if not tasks:
        safe_print("No tasks found.")
        return
    for t in tasks:
        status_icon = {"pending": "[PEND]", "claimed": "[BUSY]", "completed": "[DONE]", "failed": "[FAIL]", "cancelled": "[CANC]"}.get(t["status"], "?")
        ago = _time_ago(t.get("created_at", 0))
        desc = (t.get("description") or "")[:60]
        safe_print(f"  {status_icon} {t['task_id']} [{t['status']}] {t['title']}")
        safe_print(f"     Creator: {t.get('creator', '?')}  |  Priority: {t.get('priority', 'normal')}  |  {ago}")
        if desc:
            safe_print(f"     Desc: {desc}")
        if t.get("claimed_by"):
            safe_print(f"     Claimed by: {t['claimed_by']}")
        if t.get("result"):
            safe_print(f"     Result: {t['result'][:120]}")
        if t.get("error"):
            safe_print(f"     Error: {t['error'][:120]}")

def cmd_claim(args):
    agent_id = args.agent_id or load_agent_id()
    if not agent_id:
        print("[ERROR] No agent_id. Run register first or pass --agent-id.")
        sys.exit(1)
    result = api_post(f"/api/tasks/{args.task_id}/claim", {"agent_id": agent_id})
    if result.get("ok"):
        task = result["task"]
        print(f"[CLAIMED] {task['task_id']}: \"{task['title']}\"")
    else:
        print(f"[FAILED] {result.get('error', 'Unknown error')}")

def cmd_complete(args):
    agent_id = args.agent_id or load_agent_id()
    if not agent_id:
        print("[ERROR] No agent_id. Run register first or pass --agent-id.")
        sys.exit(1)
    result = api_post(f"/api/tasks/{args.task_id}/complete", {
        "agent_id": agent_id,
        "result": args.result or "Done."
    })
    if result.get("ok"):
        print(f"[COMPLETED] {args.task_id}")
    else:
        print(f"[FAILED] {result.get('error', 'Unknown error')}")

def cmd_fail(args):
    agent_id = args.agent_id or load_agent_id()
    if not agent_id:
        safe_print("[ERROR] No agent_id. Run register first or pass --agent-id.")
        sys.exit(1)
    result = api_post(f"/api/tasks/{args.task_id}/fail", {
        "agent_id": agent_id,
        "error": args.error or "Unknown error"
    })
    if result.get("ok"):
        safe_print(f"[FAILED] {args.task_id} marked as failed")
    else:
        safe_print(f"[ERROR] {result.get('error', 'Unknown error')}")

def cmd_cancel(args):
    result = api_post(f"/api/tasks/{args.task_id}/cancel", {})
    if result.get("ok"):
        task = result["task"]
        safe_print(f"[CANCELLED] {task['task_id']}: \"{task['title']}\"")
    else:
        safe_print(f"[ERROR] {result.get('error', 'Unknown error')}")

# ── Original commands ───────────────────────────────────────────

def cmd_send(args):
    api_post("/api/send", {"sender": args.name, "content": args.msg})
    print(f"[{args.name}] {args.msg}")

def cmd_read(args):
    path = "/api/messages"
    if args.since:
        path += f"?since={args.since}"
    msgs = api_get(path)
    for m in msgs[-20:]:
        t = time.strftime("%H:%M:%S", time.localtime(m["ts"]))
        sender = m.get("sender", "?")
        content = m.get("content", "")
        etype = m.get("type", "chat")
        prefix = {"task_create": "[TASK]", "task_claim": "[CLAIM]", "task_complete": "[DONE]",
                  "task_fail": "[FAIL]", "agent_register": "[JOIN]", "agent_offline": "[LEFT]"}.get(etype, "")
        safe_print(f"[{t}] {prefix} {sender}: {content}")

def cmd_listen(args):
    safe_print(f" Listening on {HOST}...")
    last_ts = time.time()
    while True:
        try:
            msgs = api_get(f"/api/messages?since={last_ts}")
            for m in msgs:
                if m.get("sender") == os.environ.get("AGENT_NAME"):
                    continue
                t = time.strftime("%H:%M:%S", time.localtime(m["ts"]))
                etype = m.get("type", "chat")
                content = m.get("content", "")
                prefix = {"task_create": "[TASK]", "task_claim": "[CLAIM]", "task_complete": "[DONE]",
                          "task_fail": "[FAIL]", "agent_register": "[JOIN]", "agent_offline": "[LEFT]"}.get(etype, "")
                safe_print(f"[{t}] {prefix} {m.get('sender', '?')}: {content}")
            if msgs:
                last_ts = max(m["ts"] for m in msgs)
        except Exception:
            pass
        time.sleep(1)

# ── Helpers ─────────────────────────────────────────────────────

def _parse_caps(caps_str):
    if not caps_str:
        return []
    return [c.strip() for c in caps_str.split(",") if c.strip()]

def safe_print(msg):
    """Print safely, replacing chars that can't be encoded on Windows GBK."""
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode("ascii"))

def _time_ago(ts):
    if not ts:
        return ""
    sec = max(0, time.time() - ts)
    if sec < 60:
        return f"{int(sec)}s ago"
    if sec < 3600:
        return f"{int(sec/60)}m ago"
    if sec < 86400:
        return f"{int(sec/3600)}h ago"
    return f"{int(sec/86400)}d ago"

def _count_pending_tasks():
    try:
        tasks = api_get("/api/tasks?status=pending")
        return len(tasks) if isinstance(tasks, list) else 0
    except Exception:
        return 0

def _count_matching_tasks(caps):
    try:
        tasks = api_get("/api/tasks?status=pending")
        if not isinstance(tasks, list):
            return 0
        return sum(1 for t in tasks if set(t.get("required_capabilities", [])).issubset(set(caps)))
    except Exception:
        return 0


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="A2A Agent Client")
    sp = p.add_subparsers(dest="cmd")

    # register
    sp_reg = sp.add_parser("register", help="Register with the chat platform")
    sp_reg.add_argument("--name", required=True)
    sp_reg.add_argument("--capabilities", default="")

    # auto
    sp_auto = sp.add_parser("auto", help="Auto mode: register, poll, claim, execute")
    sp_auto.add_argument("--name", required=True)
    sp_auto.add_argument("--capabilities", default="")
    sp_auto.add_argument("--poll-interval", type=int, default=5)
    sp_auto.add_argument("--verbose", action="store_true", help="Print polling status each tick")
    sp_auto.add_argument("--once", action="store_true", help="Process one task and exit")

    # heartbeat
    sp_hb = sp.add_parser("heartbeat", help="Send heartbeat")
    sp_hb.add_argument("--agent-id", default=None)

    # create-task
    sp_ct = sp.add_parser("create-task", help="Create a new task")
    sp_ct.add_argument("--title", required=True)
    sp_ct.add_argument("--desc", default="")
    sp_ct.add_argument("--capabilities", default="")
    sp_ct.add_argument("--priority", default="normal")
    sp_ct.add_argument("--creator", default="Anonymous")

    # tasks
    sp_ts = sp.add_parser("tasks", help="List tasks")
    sp_ts.add_argument("--status", default=None)

    # claim
    sp_cl = sp.add_parser("claim", help="Claim a task")
    sp_cl.add_argument("--task-id", required=True)
    sp_cl.add_argument("--agent-id", default=None)

    # complete
    sp_cp = sp.add_parser("complete", help="Complete a task")
    sp_cp.add_argument("--task-id", required=True)
    sp_cp.add_argument("--result", default=None)
    sp_cp.add_argument("--agent-id", default=None)

    # fail
    sp_fl = sp.add_parser("fail", help="Mark a task as failed")
    sp_fl.add_argument("--task-id", required=True)
    sp_fl.add_argument("--error", default=None)
    sp_fl.add_argument("--agent-id", default=None)

    # cancel
    sp_cancel = sp.add_parser("cancel", help="Cancel a task")
    sp_cancel.add_argument("--task-id", required=True)

    # Original commands
    sp_send = sp.add_parser("send", help="Send a chat message")
    sp_send.add_argument("--name", required=True)
    sp_send.add_argument("--msg", required=True)

    sp_read = sp.add_parser("read", help="Read recent messages")
    sp_read.add_argument("--since", type=float, default=0)

    sp.add_parser("listen", help="Listen for messages continuously")

    args = p.parse_args()

    if args.cmd == "register":
        cmd_register(args)
    elif args.cmd == "auto":
        cmd_auto(args)
    elif args.cmd == "heartbeat":
        cmd_heartbeat(args)
    elif args.cmd == "create-task":
        cmd_create_task(args)
    elif args.cmd == "tasks":
        cmd_tasks(args)
    elif args.cmd == "claim":
        cmd_claim(args)
    elif args.cmd == "complete":
        cmd_complete(args)
    elif args.cmd == "fail":
        cmd_fail(args)
    elif args.cmd == "cancel":
        cmd_cancel(args)
    elif args.cmd == "send":
        cmd_send(args)
    elif args.cmd == "read":
        cmd_read(args)
    elif args.cmd == "listen":
        cmd_listen(args)
    else:
        p.print_help()
