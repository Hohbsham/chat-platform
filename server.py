"""
A2A Chat Platform v3 — "The Small Restaurant"
- One asyncio event loop for HTTP + WebSocket (single port)
- SQLite database (not JSON files)
- Server pushes tasks to agents — no polling needed
- Agents connect via WebSocket, server assigns work proactively
"""
import asyncio, json, time, os, sys, uuid, re
from urllib.parse import urlparse, parse_qs
from websockets.asyncio.server import serve

import db
from logger import a2a_logger as log

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Load .env
_env_path = os.path.join(BASE_DIR, ".env")
if os.path.exists(_env_path):
    with open(_env_path, "r", encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

PORT = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[1] == "--port" else 8765
SVR_STARTED = time.time()

# Connected clients: {client_id: websocket}
ws_clients = {}
# Agent WS connections for push: {agent_id: websocket}
agent_ws = {}

# ── Event broadcasting ───────────────────────────────────────────

async def broadcast(payload):
    """Send to all WebSocket clients."""
    dead = []
    for cid, ws in list(ws_clients.items()):
        try:
            await ws.send(payload)
        except Exception:
            dead.append(cid)
    for cid in dead:
        ws_clients.pop(cid, None)


def emit_event(msg_type, sender, content, meta=None):
    """Store message + broadcast to all WS clients + push to relevant agent."""
    msg = db.message_append(msg_type, sender, content, meta)
    payload = json.dumps(msg, ensure_ascii=False)

    # Schedule on the event loop
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(broadcast(payload))

        # If task is created/claimed, push to matching agents
        if msg_type == "task_create" and meta and meta.get("task_id"):
            loop.create_task(_push_task_to_agents(meta["task_id"]))
    except RuntimeError:
        pass  # Not in async context (shouldn't happen in v3)

    return msg


def _fire_webhook(task_id, title, assigned_to):
    """Fire-and-forget POST to Channel (8788) + Hub (8767). Never blocks."""
    try:
        import urllib.request
        data = json.dumps({
            "task_id": task_id, "title": title,
            "agent": assigned_to, "ts": time.time()
        }).encode()
        # Push to Claude Channel (direct notification in window)
        try:
            req = urllib.request.Request("http://127.0.0.1:8788/",
                data=data, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=2)
        except Exception:
            pass
        # Also push to Hub (inbox for watcher fallback)
        try:
            req = urllib.request.Request("http://localhost:8767/webhook",
                data=data, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=2)
        except Exception:
            pass
        # Wake-up is handled by the desktop-side watcher (scripts/desktop_watcher.py).
        # Server cannot spawn GUI-automation reliably — it runs as a background process.
        # We only write the signal file here. The watcher detects it and runs wake_vscode.py.
    except Exception:
        pass  # Best-effort; A2A DB is the truth


def _write_signal(agent_name, task_id, title):
    """Write a signal file so the agent's cron watcher wakes up."""
    sig_dir = os.path.join(BASE_DIR, "signals")
    os.makedirs(sig_dir, exist_ok=True)
    sig_path = os.path.join(sig_dir, f"{agent_name}.json")
    try:
        with open(sig_path, "w", encoding="utf-8") as f:
            json.dump({"task_id": task_id, "title": title, "ts": time.time()}, f)
    except Exception:
        pass

# ── Claim lease enforcement ─────────────────────────────────────

CLAIM_LEASE_SECONDS = 300  # 5 minutes — claimed tasks auto-rollback

def _cleanup_expired_claims():
    """Release tasks claimed >5min ago back to pending. Runs on health check + auto-claim."""
    now = time.time()
    all_tasks = db.task_all()
    released = 0
    for t in all_tasks:
        if t.get("status") == "claimed" and t.get("claimed_at"):
            if now - t["claimed_at"] > CLAIM_LEASE_SECONDS:
                db.task_update(t["task_id"], status="pending",
                              claimed_by=None, claimed_at=None)
                db.agent_set_status(t.get("claimed_by",""), "online", None)
                log.info("Lease expired", task_id=t["task_id"][:12],
                        claimed_by=t.get("claimed_by","")[:20])
                released += 1
    if released:
        log.info("Claim cleanup", released=released)


def _notify_next_in_pipeline(completed_task_id):
    """
    After a task completes, find dependent tasks and notify their assigned agents.
    This makes pipelines run immediately — no waiting for next poll cycle.
    """
    try:
        all_tasks = db.task_all()
        dependents = [t for t in all_tasks
                      if t.get("context") and completed_task_id in t["context"]
                      and t.get("status") == "pending"]
        for dep in dependents:
            assigned = dep.get("assigned_to", "")
            if assigned:
                _write_signal(assigned, dep.get("task_id"), dep.get("title", ""))
                _fire_webhook(dep.get("task_id"), dep.get("title",""), assigned)
                log.info("Pipeline advance", done=completed_task_id[:12],
                        next=dep.get("task_id","?")[:12], to=assigned)
                emit_event("pipeline_advance", "System",
                    f"依赖完成 → 「{dep.get('title','')}」可以开始了",
                    {"task_id": dep.get("task_id"), "assigned_to": assigned})
                # Push directly to assigned agent's WebSocket
                for aid, ws in list(agent_ws.items()):
                    a = db.agent_find(aid)
                    if a and a.get("name") == assigned:
                        try:
                            asyncio.get_running_loop().create_task(
                                ws.send(json.dumps({
                                    "type": "task_ready",
                                    "task_id": dep.get("task_id"),
                                    "title": dep.get("title",""),
                                    "note": "Your dependency just completed!"
                                }, ensure_ascii=False)))
                        except Exception:
                            pass
            else:
                emit_event("pipeline_advance", "System",
                    f"依赖完成 → 「{dep.get('title','')}」等待认领",
                    {"task_id": dep.get("task_id")})
    except Exception as e:
        log.error("Pipeline notify error", error=str(e))


async def _push_task_to_agents(task_id):
    """Find online agents that can handle this task and push to them."""
    task = db.task_find(task_id)
    if not task:
        return
    required = set(task.get("required_capabilities", []))
    for agent_id, ws in list(agent_ws.items()):
        agent = db.agent_find(agent_id)
        if not agent or agent["status"] == "offline":
            continue
        caps = set(agent.get("capabilities", []))
        if required.issubset(caps):
            try:
                await ws.send(json.dumps({
                    "type": "task_available",
                    "task": task,
                }, ensure_ascii=False))
            except Exception:
                agent_ws.pop(agent_id, None)


# ── HTTP request handler ─────────────────────────────────────────

def _json_response(data, status=200):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Access-Control-Allow-Origin": "*",
    }
    return status, headers, body


def _static_response(filename):
    path = os.path.join(BASE_DIR, filename)
    if not os.path.exists(path):
        return 404, {}, b"Not found"
    ct = {"json": "application/json", "js": "application/javascript",
          "png": "image/png", "ico": "image/x-icon",
          "css": "text/css"}.get(filename.rsplit(".", 1)[-1], "application/octet-stream")
    with open(path, "rb") as f:
        return 200, {"Content-Type": ct, "Access-Control-Allow-Origin": "*"}, f.read()


def _html_response():
    html_path = os.path.join(BASE_DIR, "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return 200, {"Content-Type": "text/html; charset=utf-8",
                     "Access-Control-Allow-Origin": "*"}, f.read().encode("utf-8")


def handle_http(path, method, query, body_bytes):
    """Route HTTP requests. Returns (status, headers, body_bytes)."""
    start = time.time()
    cors_headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    }

    if method == "OPTIONS":
        return 200, cors_headers, b""

    # ── GET routes ──────────────────────────────────────────
    if method == "GET":
        # Static files
        if path in ("/manifest.json", "/service-worker.js",
                     "/icon-192.png", "/icon-512.png"):
            status, headers, body = _static_response(path[1:])
            headers.update(cors_headers)
            _log_req("GET", path, status, start)
            return status, headers, body

        if path in ("/", ""):
            status, headers, body = _html_response()
            headers.update(cors_headers)
            _log_req("GET", path, status, start)
            return status, headers, body

        if path == "/api/health":
            _cleanup_expired_claims()  # Enforce claim leases
            h = db.db_health()
            h.update({
                "ok": True,
                "uptime": round(time.time() - SVR_STARTED, 1),
                "ws_clients": len(ws_clients),
                "agent_ws_count": len(agent_ws),
            })
            _log_req("GET", path, 200, start)
            return _json_response(h)

        if path == "/api/messages":
            since = float(query.get("since", [0])[0]) if query.get("since") else 0
            msgs = db.message_all(since)
            _log_req("GET", path, 200, start)
            return _json_response(msgs)

        if path == "/api/agents":
            status_filter = query.get("status", [None])[0]
            alist = db.agent_all()
            if status_filter and status_filter != "all":
                alist = [a for a in alist if a.get("status") == status_filter]
            # Default: show all agents. "Offline" is meaningless — watcher handles liveness.
            _log_req("GET", path, 200, start)
            return _json_response(alist)

        if path == "/api/tasks":
            status_filter = query.get("status", [None])[0]
            tlist = db.task_all()
            if status_filter:
                tlist = [t for t in tlist if t.get("status") == status_filter]
            _log_req("GET", path, 200, start)
            return _json_response(tlist)

        # /api/tasks/<id>
        if (m := re.match(r"^/api/tasks/([^/]+)$", path)):
            task = db.task_find(m.group(1))
            if task:
                _log_req("GET", path, 200, start)
                return _json_response(task)
            _log_req("GET", path, 404, start)
            return _json_response({"ok": False, "error": "Task not found", "code": "TASK_NOT_FOUND"}, 404)

        # /api/tasks/<id>/timeline
        if (m := re.match(r"^/api/tasks/([^/]+)/timeline$", path)):
            task = db.task_find(m.group(1))
            if task:
                timeline = db.message_task_timeline(task["task_id"])
                _log_req("GET", path, 200, start)
                return _json_response({"task": task, "timeline": timeline})
            _log_req("GET", path, 404, start)
            return _json_response({"ok": False, "error": "Task not found", "code": "TASK_NOT_FOUND"}, 404)

        _log_req("GET", path, 404, start)
        return 404, cors_headers, b"Not found"

    # ── POST routes ─────────────────────────────────────────
    if method == "POST":
        try:
            data = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            _log_req("POST", path, 400, start)
            return _json_response({"ok": False, "error": "Invalid JSON", "code": "INVALID_JSON"}, 400)

        # Chat
        if path == "/api/send":
            msg = emit_event("chat", data.get("sender", "?"), data.get("content", ""))
            _log_req("POST", path, 200, start)
            return _json_response({"ok": True, "msg": msg})

        # Agent register
        if path == "/api/agents/register":
            agent_id = data.get("agent_id", "")
            verified = data.get("verified", False)
            source = data.get("source", "unknown")
            name = data.get("name", "Unknown")

            # Dedup: if no agent_id given, find existing agent with same name+source
            if not agent_id:
                existing = db.agent_find_by_name_source(name, source)
                if existing:
                    agent_id = existing["agent_id"]
                else:
                    agent_id = f"{name}-{uuid.uuid4().hex[:6]}"

            agent, warning = db.agent_register(
                agent_id=agent_id, name=name,
                role=data.get("role", ""), goal=data.get("goal", ""),
                backstory=data.get("backstory", ""),
                capabilities=data.get("capabilities", []),
                model=data.get("model", ""),
                verified=verified,
                source=source,
            )
            caps_str = ", ".join(agent.get("capabilities", [])) if agent.get("capabilities") else "none"
            identity = agent.get("role") or agent.get("name")
            vflag = " [VERIFIED]" if agent.get("verified") else " [UNVERIFIED]"
            meta = {"agent_id": agent_id, "capabilities": agent.get("capabilities"),
                     "role": agent.get("role"), "goal": agent.get("goal"),
                     "verified": agent.get("verified"),
                     "source": agent.get("source")}
            if warning:
                meta["warning"] = warning
                log.warning("Capability downgrade", agent=agent_id, warning=warning)
            emit_event("agent_register", agent.get("name"),
                f"{identity} 上线{vflag} — 能力: {caps_str}", meta)
            _log_req("POST", path, 200, start)
            resp = {"ok": True, "agent": agent}
            if warning:
                resp["warning"] = warning
            return _json_response(resp)

        # Agent unregister
        if path == "/api/agents/unregister":
            agent_id = data.get("agent_id", "")
            a = db.agent_find(agent_id)
            if a:
                db.agent_unregister(agent_id)
                db.task_cancel_stale(agent_id)
                emit_event("agent_offline", a.get("name"), f"{a.get('name')} 离线了",
                          {"agent_id": agent_id})
                agent_ws.pop(agent_id, None)
                _log_req("POST", path, 200, start)
                return _json_response({"ok": True})
            _log_req("POST", path, 404, start)
            return _json_response({"ok": False, "error": "Agent not found", "code": "AGENT_NOT_FOUND"}, 404)

        # Agent heartbeat
        if path == "/api/agents/heartbeat":
            agent_id = data.get("agent_id", "")
            if db.agent_heartbeat(agent_id):
                _log_req("POST", path, 200, start)
                return _json_response({"ok": True})
            _log_req("POST", path, 404, start)
            return _json_response({"ok": False, "error": "Agent not found", "code": "AGENT_NOT_FOUND"}, 404)

        # Agent progress report
        if path == "/api/agents/progress":
            agent_id = data.get("agent_id", "")
            agent = db.agent_find(agent_id)
            if agent:
                emit_event("task_working", agent.get("name"),
                    f"{agent.get('name')} {data.get('status', 'working...')}",
                    {"agent_id": agent_id, "task_id": data.get("task_id", ""),
                     "status": data.get("status", "")})
                _log_req("POST", path, 200, start)
                return _json_response({"ok": True})
            _log_req("POST", path, 404, start)
            return _json_response({"ok": False, "error": "Agent not found", "code": "AGENT_NOT_FOUND"}, 404)

        # Task create
        if path == "/api/tasks":
            task = db.task_create(
                title=data.get("title", "Untitled"),
                description=data.get("description", ""),
                required_capabilities=data.get("required_capabilities", []),
                priority=data.get("priority", "normal"),
                creator=data.get("creator", "Anonymous"),
                broadcast=data.get("broadcast", False),
                context=data.get("context", []),
                max_rounds=data.get("max_rounds", 0),
                approval_required=data.get("approval_required", False),
                assigned_to=data.get("assigned_to", ""),
            )
            broadcast_tag = "[广播] " if task.get("broadcast") else ""
            emit_event("task_create", task.get("creator"),
                f"{broadcast_tag}[新任务] {task.get('title')}",
                {"task_id": task.get("task_id"), "title": task.get("title"),
                 "description": task.get("description"),
                 "required_capabilities": task.get("required_capabilities"),
                 "priority": task.get("priority"), "broadcast": task.get("broadcast"),
                 "context": task.get("context"), "max_rounds": task.get("max_rounds"),
                 "approval_required": task.get("approval_required")})
            _log_req("POST", path, 200, start)
            # ── Wake up assigned agent via signal + webhook ──
            assigned = task.get("assigned_to", "")
            if assigned:
                _write_signal(assigned, task["task_id"], task["title"])
                _fire_webhook(task["task_id"], task["title"], assigned)
            return _json_response({"ok": True, "task": task})

        # Task actions: /api/tasks/<id>/<action>
        if (m := re.match(r"^/api/tasks/([^/]+)/(claim|complete|fail|cancel|comment|approve)$", path)):
            return _handle_task_action(m.group(1), m.group(2), data, start)

        # Auto-claim
        if path == "/api/tasks/auto-claim":
            return _handle_auto_claim(data, start)

        _log_req("POST", path, 404, start)
        return 404, cors_headers, b"Not found"

    _log_req("GET", path, 405, start)
    return 405, cors_headers, b"Method not allowed"


def _log_req(method, path, status, start):
    elapsed = round((time.time() - start) * 1000)
    if elapsed > 500:
        log.warning("SLOW", method=method, path=path, status=status, elapsed_ms=elapsed)


# ── Task action handlers ─────────────────────────────────────────

def _handle_task_action(task_id, action, data, start):
    task = db.task_find(task_id)
    if not task:
        _log_req("POST", f"/api/tasks/{task_id}/{action}", 404, start)
        return _json_response({"ok": False, "error": "Task not found", "code": "TASK_NOT_FOUND"}, 404)

    agent_id = data.get("agent_id", "")
    agent = db.agent_find(agent_id)
    agent_name = agent.get("name") if agent else agent_id
    now = time.time()

    if action == "claim":
        if task["status"] not in ("pending", "input_required"):
            return _json_response({"ok": False, "error": f"Task is {task['status']}", "code": "INVALID_STATE"}, 400)
        if task["broadcast"]:
            db.agent_set_status(agent_id, "busy", task_id)
            emit_event("task_claim", agent_name, f"{agent_name} 参与广播: {task['title']}",
                      {"task_id": task_id, "agent_name": agent_name})
            emit_event("task_working", agent_name, f"⚙ {agent_name} 开始处理「{task['title']}」...",
                      {"task_id": task_id, "agent_name": agent_name, "status": "thinking"})
        else:
            speaker_queue = task.get("speaker_queue", [])
            if task.get("max_rounds", 0) > 0 and agent_id not in speaker_queue:
                speaker_queue = list(speaker_queue) + [agent_id]
            db.task_update(task_id, status="claimed", claimed_by=agent_id, claimed_at=now,
                          speaker_queue=speaker_queue)
            db.agent_set_status(agent_id, "busy", task_id)
            emit_event("task_claim", agent_name, f"{agent_name} 领取了任务: {task['title']}",
                      {"task_id": task_id, "claimed_by": agent_id, "agent_name": agent_name})
            emit_event("task_working", agent_name, f"⚙ {agent_name} 正在分析「{task['title']}」...",
                      {"task_id": task_id, "agent_name": agent_name, "status": "thinking"})
        _log_req("POST", f"/api/tasks/{task_id}/claim", 200, start)
        return _json_response({"ok": True, "task": db.task_find(task_id)})

    elif action == "complete":
        result = data.get("result", "")
        if task["broadcast"]:
            responses = list(task.get("responses", []))
            existing = next((r for r in responses if r.get("agent_id") == agent_id), None)
            if existing:
                existing["result"] = result
                existing["completed_at"] = now
            else:
                responses.append({"agent_id": agent_id, "agent_name": agent_name,
                                  "result": result, "completed_at": now})
            db.task_update(task_id, responses=responses)
            db.agent_set_status(agent_id, "online", None)
            emit_event("broadcast_response", agent_name,
                f"📢 {agent_name} 回复了「{task['title']}」", {"task_id": task_id, "response_count": len(responses)})
        elif task.get("approval_required") and not task.get("approved"):
            db.task_update(task_id, status="input_required", result=result,
                          completed_by=agent_id, completed_at=now)
            db.agent_set_status(agent_id, "online", None)
            emit_event("approval_request", agent_name,
                f"{agent_name} 提交了结果，等待审批: {task['title']}", {"task_id": task_id, "result": result})
        else:
            db.task_update(task_id, status="completed", result=result,
                          completed_by=agent_id, completed_at=now)
            db.agent_set_status(agent_id, "online", None)
            emit_event("task_complete", agent_name, f"[完成] {task['title']}",
                      {"task_id": task_id, "completed_by": agent_id, "agent_name": agent_name, "result": result})
            # Wake up agents waiting on this task's completion
            _notify_next_in_pipeline(task_id)
        _log_req("POST", f"/api/tasks/{task_id}/complete", 200, start)
        return _json_response({"ok": True, "task": db.task_find(task_id)})

    elif action == "fail":
        error = data.get("error", "Unknown error")
        if task["status"] not in ("claimed", "working"):
            return _json_response({"ok": False, "error": f"Task is {task['status']}", "code": "INVALID_STATE"}, 400)
        db.task_update(task_id, status="failed", error=error)
        db.agent_set_status(agent_id, "online", None)
        emit_event("task_fail", agent_name, f"[失败] {task['title']}",
                  {"task_id": task_id, "agent_name": agent_name, "error": error})
        _log_req("POST", f"/api/tasks/{task_id}/fail", 200, start)
        return _json_response({"ok": True, "task": db.task_find(task_id)})

    elif action == "cancel":
        if task["status"] in ("completed", "failed", "cancelled"):
            return _json_response({"ok": False, "error": f"Task already {task['status']}", "code": "INVALID_STATE"}, 400)
        db.task_update(task_id, status="cancelled")
        emit_event("task_cancel", "System", f"[取消] 任务已取消: {task['title']}", {"task_id": task_id})
        _log_req("POST", f"/api/tasks/{task_id}/cancel", 200, start)
        return _json_response({"ok": True, "task": db.task_find(task_id)})

    elif action == "approve":
        if not task.get("approval_required"):
            return _json_response({"ok": False, "error": "No approval needed", "code": "INVALID_STATE"}, 400)
        if data.get("approved", True):
            db.task_update(task_id, status="completed", approved=True)
            emit_event("task_complete", data.get("approver", "Human"),
                f"[审批通过] {task['title']}", {"task_id": task_id})
        else:
            db.task_update(task_id, status="pending", result=None, completed_by=None, approved=False)
            emit_event("task_fail", data.get("approver", "Human"),
                f"[审批拒绝] {task['title']} — 已退回", {"task_id": task_id})
        _log_req("POST", f"/api/tasks/{task_id}/approve", 200, start)
        return _json_response({"ok": True, "task": db.task_find(task_id)})

    _log_req("POST", f"/api/tasks/{task_id}/{action}", 400, start)
    return _json_response({"ok": False, "error": f"Unknown action: {action}", "code": "UNKNOWN_ACTION"}, 400)


def _handle_auto_claim(data, start):
    _cleanup_expired_claims()  # Enforce claim leases before matching
    agent_id = data.get("agent_id", "")
    capabilities = data.get("capabilities", [])
    agent = db.agent_find(agent_id)
    if not agent:
        _log_req("POST", "/api/tasks/auto-claim", 400, start)
        return _json_response({"ok": False, "error": "Agent not registered", "code": "AGENT_NOT_FOUND"}, 400)
    if agent["status"] == "offline":
        _log_req("POST", "/api/tasks/auto-claim", 400, start)
        return _json_response({"ok": False, "error": "Agent is offline", "code": "AGENT_OFFLINE"}, 400)

    db.agent_heartbeat(agent_id)
    all_tasks = db.task_all()
    priority_order = {"high": 0, "normal": 1, "low": 2}
    agent_name = agent.get("name", "")

    # Two-pass matching: assigned tasks first, then unassigned
    assigned_matching = []
    unassigned_matching = []

    for t in all_tasks:
        required = set(t.get("required_capabilities", []))
        # Empty caps = "not specified yet", don't match anyone.
        # Otherwise set().issubset(ANY) is always True → Hermes steals everything.
        if not required:
            continue
        if not required.issubset(set(capabilities)):
            continue

        # Honor assignment: skip tasks explicitly assigned to someone else
        assigned_to = t.get("assigned_to", "")
        if assigned_to and assigned_to != agent_name:
            continue  # Don't steal other agents' tasks

        # Context dependencies
        if t.get("context"):
            deps_done = all(
                (dt := db.task_find(d)) and dt.get("status") == "completed"
                for d in t["context"]
            )
            if not deps_done:
                continue

        if t["status"] == "pending":
            if t.get("broadcast"):
                existing_ids = [r.get("agent_id", "") for r in t.get("responses", [])]
                if agent_id not in existing_ids:
                    (assigned_matching if assigned_to else unassigned_matching).append(t)
            elif t.get("max_rounds", 0) > 0:
                if t.get("current_round", 0) < t["max_rounds"]:
                    (assigned_matching if assigned_to else unassigned_matching).append(t)
            else:
                (assigned_matching if assigned_to else unassigned_matching).append(t)
        elif t["status"] == "input_required" and t.get("claimed_by") == agent_id:
            (assigned_matching if assigned_to else unassigned_matching).append(t)

    # Priority: assigned tasks first, then unassigned
    sort_key = lambda t: (priority_order.get(t.get("priority", "normal"), 1), t.get("created_at", 0))
    assigned_matching.sort(key=sort_key)
    unassigned_matching.sort(key=sort_key)
    matching = assigned_matching + unassigned_matching

    if not matching:
        _log_req("POST", "/api/tasks/auto-claim", 200, start)
        return _json_response({"ok": True, "claimed": None})

    best = matching[0]
    # GroupChat speaker order
    if best.get("max_rounds", 0) > 0 and best.get("speaker_queue"):
        sq = best["speaker_queue"]
        next_idx = best.get("current_round", 0) % len(sq)
        if agent_id != sq[next_idx]:
            return _json_response({"ok": True, "claimed": None, "note": f"Waiting for speaker {sq[next_idx]}"})

    # Perform claim
    now = time.time()
    if best.get("broadcast"):
        db.agent_set_status(agent_id, "busy", best["task_id"])
        emit_event("task_claim", agent.get("name"), f"{agent.get('name')} 参与广播: {best['title']}",
                  {"task_id": best["task_id"], "agent_name": agent.get("name")})
    else:
        sq = list(best.get("speaker_queue", []))
        if best.get("max_rounds", 0) > 0 and agent_id not in sq:
            sq.append(agent_id)
        db.task_update(best["task_id"], status="claimed", claimed_by=agent_id, claimed_at=now,
                      speaker_queue=sq)
        db.agent_set_status(agent_id, "busy", best["task_id"])
        emit_event("task_claim", agent.get("name"), f"{agent.get('name')} 领取了任务: {best['title']}",
                  {"task_id": best["task_id"], "agent_name": agent.get("name")})
        emit_event("task_working", agent.get("name"), f"⚙ {agent.get('name')} 正在分析「{best['title']}」...",
                  {"task_id": best["task_id"], "agent_name": agent.get("name"), "status": "thinking"})

    result = {"ok": True, "claimed": db.task_find(best["task_id"])}
    if best.get("context"):
        result["context_results"] = [
            {"task_id": d, "title": (dt["title"] if (dt := db.task_find(d)) else "?"),
             "result": (dt.get("result") if dt else None)}
            for d in best["context"]
        ]
    if best.get("max_rounds", 0) > 0:
        result["round"] = best.get("current_round", 0) + 1
        result["max_rounds"] = best["max_rounds"]

    _log_req("POST", "/api/tasks/auto-claim", 200, start)
    return _json_response(result)


# ── WebSocket handler ────────────────────────────────────────────

async def ws_handler(websocket):
    """Handle WebSocket connection. Supports both web UI clients and agents."""
    client_id = uuid.uuid4().hex[:8]
    ws_clients[client_id] = websocket
    registered_agent_id = None

    try:
        # Send initial state
        await websocket.send(json.dumps({
            "type": "connected",
            "client_id": client_id,
            "agents": db.agent_all(),
            "tasks": db.task_all(),
        }, ensure_ascii=False))

        async for raw_msg in websocket:
            try:
                msg = json.loads(raw_msg)
                msg_type = msg.get("type", "")

                if msg_type == "ping":
                    await websocket.send(json.dumps({"type": "pong"}))

                elif msg_type == "chat":
                    emit_event("chat", msg.get("sender", "?"), msg.get("content", ""))

                elif msg_type == "agent_connect":
                    # Agent registers its WS connection for push
                    agent_id = msg.get("agent_id", "")
                    if agent_id:
                        registered_agent_id = agent_id
                        agent_ws[agent_id] = websocket
                        db.agent_heartbeat(agent_id)
                        await websocket.send(json.dumps({"type": "agent_connected", "agent_id": agent_id}))

                elif msg_type == "agent_heartbeat":
                    if registered_agent_id:
                        db.agent_heartbeat(registered_agent_id)

            except json.JSONDecodeError:
                pass
    except Exception:
        pass
    finally:
        ws_clients.pop(client_id, None)
        if registered_agent_id:
            agent_ws.pop(registered_agent_id, None)


# ── Periodic cleanup ─────────────────────────────────────────────

async def cleanup_loop():
    """Every 30s: mark timed-out agents as offline, release their tasks."""
    while True:
        await asyncio.sleep(30)
        try:
            gone = db.agent_cleanup_offline()
            for agent_id in gone:
                db.task_cancel_stale(agent_id)
                if agent_id in agent_ws:
                    agent_ws.pop(agent_id, None)
                agent = db.agent_find(agent_id)
                name = agent.get("name") if agent else agent_id
                emit_event("agent_offline", name, f"{name} 离线了（超时）", {"agent_id": agent_id})
        except Exception as e:
            log.error("Cleanup error", error=str(e))


# ── Asyncio HTTP server ────────────────────────────────────────────

class AioHTTPHandler:
    """Minimal asyncio HTTP protocol handler."""

    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer

    async def handle(self):
        try:
            raw = await asyncio.wait_for(self.reader.readuntil(b"\r\n\r\n"), timeout=30)
            header_part = raw.decode("utf-8", errors="replace")
            lines = header_part.split("\r\n")
            if not lines:
                return
            method, path, _ = lines[0].split(" ", 2)
            headers = {}
            for line in lines[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.strip().lower()] = v.strip()

            content_length = int(headers.get("content-length", 0))
            body_bytes = b""
            if content_length > 0:
                body_bytes = await asyncio.wait_for(
                    self.reader.readexactly(content_length), timeout=30)

            query = parse_qs(urlparse(path).query)
            path_only = urlparse(path).path
            status, resp_headers, resp_body = handle_http(
                path_only, method, query, body_bytes)

            # Build HTTP response
            status_text = {200: "OK", 400: "Bad Request", 404: "Not Found",
                          405: "Method Not Allowed", 500: "Internal Server Error"}.get(status, "OK")
            resp_lines = [f"HTTP/1.1 {status} {status_text}"]
            for k, v in resp_headers.items():
                resp_lines.append(f"{k}: {v}")
            resp_lines.append(f"Content-Length: {len(resp_body)}")
            resp_lines.append("")
            resp_lines.append("")
            self.writer.write("\r\n".join(resp_lines).encode("utf-8") + resp_body)
            await self.writer.drain()
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionResetError):
            pass
        except Exception as e:
            try:
                log.error("HTTP handler error", error=str(e))
            except Exception:
                pass
        finally:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception:
                pass


async def http_server_main():
    """Start the asyncio HTTP server."""
    server = await asyncio.start_server(
        lambda r, w: AioHTTPHandler(r, w).handle(),
        "0.0.0.0", PORT)
    print(f"   HTTP REST API:  http://localhost:{PORT}")
    async with server:
        await server.serve_forever()


# ── Main ─────────────────────────────────────────────────────────

WS_PORT = PORT + 1

async def main():
    log.info("A2A v3 starting", port=PORT, ws_port=WS_PORT)
    print(f"\n  A2A Chat Platform v3 — The Small Restaurant")
    print(f"   SQLite database (a2a.db)")
    print(f"   Agents: push-based via WebSocket, no polling needed\n")

    # Start cleanup task
    # Cleanup disabled — "offline" is meaningless. Watcher handles liveness.
    # asyncio.create_task(cleanup_loop())

    # Run HTTP + WebSocket servers concurrently
    await asyncio.gather(
        http_server_main(),
        serve(ws_handler, "0.0.0.0", WS_PORT),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer stopped.")
