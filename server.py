"""
A2A Chat Platform v2 — HTTP Server + WebSocket
- HTTP REST API on port 8765
- WebSocket real-time push on port 8766
- Agent identity model: role/goal/backstory (CrewAI-inspired)
- Task state machine: pending→claimed→working→input_required→completed (A2A-inspired)
- GroupChat speaker selection (AutoGen-inspired)
- Broadcast with deferred aggregation (LangGraph-inspired)
- Human-in-the-Loop approval (LangGraph-inspired)
- Task dependency context chaining (CrewAI-inspired)
"""
import asyncio, json, time, os, sys, uuid, re, threading
from urllib.parse import urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler
from websockets.asyncio.server import serve
from models import AgentStore, TaskStore, MessageStore

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PORT = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[1] == "--port" else 8765
WS_PORT = PORT + 1  # WebSocket on next port
SVR_STARTED = time.time()

agents = AgentStore()
tasks = TaskStore()
messages = MessageStore()

# Connected WebSocket clients
ws_clients = {}  # {client_id: websocket}
_ws_event_loop = None

# ── Event broadcasting ───────────────────────────────────────────

def emit_event(msg_type, sender, content, meta=None):
    """Store message + push to all WebSocket clients."""
    msg = messages.append(msg_type, sender, content, meta)
    payload = json.dumps(msg.to_dict(), ensure_ascii=False)
    # Schedule broadcast on WS event loop (thread-safe)
    if _ws_event_loop and ws_clients:
        _ws_event_loop.call_soon_threadsafe(
            lambda: asyncio.ensure_future(_broadcast(payload))
        )
    return msg

async def _broadcast(payload):
    """Send payload to all WS clients."""
    dead = []
    for cid, ws in list(ws_clients.items()):
        try:
            await ws.send(payload)
        except Exception:
            dead.append(cid)
    for cid in dead:
        ws_clients.pop(cid, None)

# ── HTTP Server ──────────────────────────────────────────────────

class ChatHTTPHandler(BaseHTTPRequestHandler):

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code, data):
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _html(self):
        html_path = os.path.join(BASE_DIR, "index.html")
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def _parse(self):
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    # ── Routing ───────────────────────────────────────────

    def do_OPTIONS(self):
        self.send_response(200); self._cors(); self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        qs = parse_qs(urlparse(self.path).query)

        if path in ("/", ""):
            self._html()
        elif path == "/api/health":
            online = len(agents.online_agents())
            all_tasks = tasks.all()
            pending = sum(1 for t in all_tasks if t.status == "pending")
            self._json(200, {
                "ok": True, "agents_online": online, "agents_total": agents.count(),
                "tasks_pending": pending, "tasks_total": len(all_tasks),
                "uptime": round(time.time() - SVR_STARTED, 1),
                "ws_port": WS_PORT,
            })
        elif path == "/api/messages":
            since = float(qs.get("since", [0])[0]) if qs.get("since") else 0
            self._json(200, messages.all(since))
        elif path == "/api/agents":
            status = qs.get("status", [None])[0]
            alist = [a.to_dict() for a in agents.all()]
            if status:
                alist = [a for a in alist if a.get("status") == status]
            self._json(200, alist)
        elif path == "/api/tasks":
            status = qs.get("status", [None])[0]
            tlist = [t.to_dict() for t in tasks.all()]
            if status:
                tlist = [t for t in tlist if t.get("status") == status]
            self._json(200, tlist)
        elif (m := re.match(r"^/api/tasks/([^/]+)$", path)):
            task = tasks.find(m.group(1))
            if task:
                self._json(200, task.to_dict())
            else:
                self._json(404, {"ok": False, "error": "Task not found"})
        elif (m := re.match(r"^/api/tasks/([^/]+)/timeline$", path)):
            task = tasks.find(m.group(1))
            if task:
                self._json(200, {"task": task.to_dict(), "timeline": messages.get_task_timeline(task.task_id)})
            else:
                self._json(404, {"ok": False, "error": "Task not found"})
        else:
            self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path
        data = self._parse()
        if data is None:
            self._json(400, {"ok": False, "error": "Invalid JSON"}); return

        # Chat
        if path == "/api/send":
            msg = emit_event("chat", data.get("sender", "?"), data.get("content", ""))
            self._json(200, {"ok": True, "msg": msg.to_dict()})

        # Agent register
        elif path == "/api/agents/register":
            agent_id = data.get("agent_id", "") or f"{data.get('name','?')}-{uuid.uuid4().hex[:6]}"
            agent = agents.register(
                agent_id=agent_id, name=data.get("name", "Unknown"),
                role=data.get("role", ""), goal=data.get("goal", ""),
                backstory=data.get("backstory", ""),
                capabilities=data.get("capabilities", []), model=data.get("model", ""),
            )
            caps_str = ", ".join(agent.capabilities) if agent.capabilities else "none"
            identity = agent.role if agent.role else agent.name
            emit_event("agent_register", agent.name,
                f"{identity} 上线 — 能力: {caps_str}",
                {"agent_id": agent_id, "capabilities": agent.capabilities, "role": agent.role, "goal": agent.goal})
            self._json(200, {"ok": True, "agent": agent.to_dict()})

        # Agent unregister
        elif path == "/api/agents/unregister":
            agent_id = data.get("agent_id", "")
            a = agents.find(agent_id)
            if a:
                agents.unregister(agent_id); tasks.cancel_stale_claims(agent_id)
                emit_event("agent_offline", a.name, f"{a.name} 离线了", {"agent_id": agent_id})
                self._json(200, {"ok": True})
            else:
                self._json(404, {"ok": False, "error": "Agent not found"})

        # Agent heartbeat
        elif path == "/api/agents/heartbeat":
            agent_id = data.get("agent_id", "")
            if agents.heartbeat(agent_id):
                self._json(200, {"ok": True})
            else:
                self._json(404, {"ok": False, "error": "Agent not found"})

        # Task create
        elif path == "/api/tasks":
            task = tasks.create(
                title=data.get("title", "Untitled"),
                description=data.get("description", ""),
                required_capabilities=data.get("required_capabilities", []),
                priority=data.get("priority", "normal"),
                creator=data.get("creator", "Anonymous"),
                broadcast=data.get("broadcast", False),
                context=data.get("context", []),
                max_rounds=data.get("max_rounds", 0),
                approval_required=data.get("approval_required", False),
            )
            broadcast_tag = "[广播] " if task.broadcast else ""
            grp_tag = f"[群聊 {task.max_rounds}轮] " if task.max_rounds else ""
            deps_tag = f" (依赖: {', '.join(task.context)})" if task.context else ""
            emit_event("task_create", task.creator,
                f"{broadcast_tag}{grp_tag}[新任务] {task.title}{deps_tag}",
                {"task_id": task.task_id, "title": task.title, "description": task.description,
                 "required_capabilities": task.required_capabilities, "priority": task.priority,
                 "broadcast": task.broadcast, "context": task.context, "max_rounds": task.max_rounds,
                 "approval_required": task.approval_required})
            self._json(200, {"ok": True, "task": task.to_dict()})

        # Task actions
        elif (m := re.match(r"^/api/tasks/([^/]+)/(claim|complete|fail|cancel|comment|approve)$", path)):
            self._handle_action(m.group(1), m.group(2), data)

        # Auto-claim
        elif path == "/api/tasks/auto-claim":
            self._handle_auto_claim(data)

        # Notify legacy
        elif path == "/api/notify":
            agent_id = data.get("agent_id", f"legacy-{data.get('name','?')}")
            agents.register(agent_id=agent_id, name=data.get("name", "?"), capabilities=data.get("capabilities", []))
            self._json(200, {"ok": True, "note": "deprecated"})
        else:
            self.send_error(404)

    def log_message(self, format, *args):
        pass  # Silent

    # ── Task action helpers ───────────────────────────────

    def _handle_action(self, task_id, action, data):
        task = tasks.find(task_id)
        if not task:
            self._json(404, {"ok": False, "error": "Task not found"}); return
        agent_id = data.get("agent_id", "")
        agent = agents.find(agent_id)
        agent_name = agent.name if agent else agent_id
        now = time.time()

        if action == "claim":
            if task.status not in ("pending", "input_required"):
                self._json(400, {"ok": False, "error": f"Task is {task.status}"}); return
            if task.broadcast:
                agents.set_status(agent_id, "busy", task_id)
                emit_event("task_claim", agent_name, f"{agent_name} 参与广播: {task.title}",
                           {"task_id": task_id, "claimed_by": agent_id, "agent_name": agent_name})
            else:
                if task.max_rounds > 0 and agent_id not in task.speaker_queue:
                    task.speaker_queue.append(agent_id)
                tasks.update(task_id, status="claimed", claimed_by=agent_id, claimed_at=now,
                             speaker_queue=task.speaker_queue)
                agents.set_status(agent_id, "busy", task_id)
                emit_event("task_claim", agent_name, f"{agent_name} 领取了任务: {task.title}",
                           {"task_id": task_id, "claimed_by": agent_id, "agent_name": agent_name})
            self._json(200, {"ok": True, "task": tasks.find(task_id).to_dict()})

        elif action == "complete":
            result = data.get("result", "")
            if task.broadcast:
                # Convert all to plain dicts for safe JSON serialization
                responses = [{k:v for k,v in (r.items() if isinstance(r, dict) else r.to_dict().items())}
                            for r in task.responses]
                existing = [r for r in responses if r.get('agent_id') == agent_id]
                if existing:
                    existing[0]['result'] = result
                    existing[0]['completed_at'] = now
                else:
                    responses.append({"agent_id": agent_id, "agent_name": agent_name,
                                      "result": result, "completed_at": now})
                tasks.update(task_id, responses=responses)
                agents.set_status(agent_id, "online", None)
                n = len(responses)
                emit_event("broadcast_response", agent_name,
                    f"📢 {agent_name} 回复了「{task.title}」：\n{result}",
                    {"task_id": task_id, "agent_name": agent_name, "result": result,
                     "broadcast": True, "response_count": n, "title": task.title})
            elif task.approval_required and not task.approved:
                tasks.update(task_id, status="input_required", result=result, completed_by=agent_id, completed_at=now)
                agents.set_status(agent_id, "online", None)
                emit_event("approval_request", agent_name,
                    f"{agent_name} 提交了结果，等待审批: {task.title}",
                    {"task_id": task_id, "agent_name": agent_name, "result": result})
            else:
                tasks.update(task_id, status="completed", result=result, completed_by=agent_id, completed_at=now)
                agents.set_status(agent_id, "online", None)
                emit_event("task_complete", agent_name, f"[完成] {task.title}",
                           {"task_id": task_id, "completed_by": agent_id, "agent_name": agent_name, "result": result})
            self._json(200, {"ok": True, "task": tasks.find(task_id).to_dict()})

        elif action == "fail":
            error = data.get("error", "Unknown error")
            if task.status not in ("claimed", "working"):
                self._json(400, {"ok": False, "error": f"Task is {task.status}"}); return
            tasks.update(task_id, status="failed", error=error)
            agents.set_status(agent_id, "online", None)
            emit_event("task_fail", agent_name, f"[失败] {task.title}",
                       {"task_id": task_id, "failed_by": agent_id, "agent_name": agent_name, "error": error})
            self._json(200, {"ok": True, "task": tasks.find(task_id).to_dict()})

        elif action == "cancel":
            if task.status in ("completed", "failed", "cancelled"):
                self._json(400, {"ok": False, "error": f"Task already {task.status}"}); return
            tasks.update(task_id, status="cancelled")
            emit_event("task_cancel", "System", f"[取消] 任务已取消: {task.title}", {"task_id": task_id})
            self._json(200, {"ok": True, "task": tasks.find(task_id).to_dict()})

        elif action == "comment":
            content = data.get("content", "")
            if not content.strip():
                self._json(400, {"ok": False, "error": "content required"}); return
            emit_event("task_comment", data.get("sender", "?"), content, {"task_id": task_id})
            self._json(200, {"ok": True})

        elif action == "approve":
            if not task.approval_required:
                self._json(400, {"ok": False, "error": "No approval needed"}); return
            if data.get("approved", True):
                tasks.update(task_id, status="completed", approved=True)
                emit_event("task_complete", data.get("approver", "Human"),
                    f"[审批通过] {task.title}",
                    {"task_id": task_id, "result": task.result})
            else:
                tasks.update(task_id, status="pending", result=None, completed_by=None, approved=False)
                emit_event("task_fail", data.get("approver", "Human"),
                    f"[审批拒绝] {task.title} — 已退回",
                    {"task_id": task_id})
            self._json(200, {"ok": True, "task": tasks.find(task_id).to_dict()})

    def _handle_auto_claim(self, data):
        agent_id = data.get("agent_id", "")
        capabilities = data.get("capabilities", [])
        agent = agents.find(agent_id)
        if not agent:
            self._json(400, {"ok": False, "error": "Agent not registered"}); return
        if agent.status == "offline":
            self._json(400, {"ok": False, "error": "Agent is offline"}); return

        agents.heartbeat(agent_id)
        all_tasks = tasks.all()
        priority_order = {"high": 0, "normal": 1, "low": 2}
        matching = []

        for t in all_tasks:
            required = set(t.required_capabilities)
            if not required.issubset(set(capabilities)):
                continue
            # Context dependencies
            if t.context:
                deps_done = all((dt := tasks.find(d)) and dt.status == "completed" for d in t.context)
                if not deps_done:
                    continue

            if t.status == "pending":
                if t.broadcast:
                    existing_ids = [getattr(r,'agent_id',r.get('agent_id','')) for r in t.responses]
                    if agent_id not in existing_ids:
                        matching.append(t)
                elif t.max_rounds > 0:
                    if t.current_round < t.max_rounds:
                        matching.append(t)
                else:
                    matching.append(t)
            elif t.status == "input_required" and t.claimed_by == agent_id:
                matching.append(t)

        matching.sort(key=lambda t: (priority_order.get(t.priority, 1), t.created_at))
        if not matching:
            self._json(200, {"ok": True, "claimed": None}); return

        best = matching[0]
        # GroupChat speaker order
        if best.max_rounds > 0 and best.speaker_queue:
            next_idx = best.current_round % len(best.speaker_queue)
            if agent_id != best.speaker_queue[next_idx]:
                self._json(200, {"ok": True, "claimed": None, "note": "Not your turn"}); return

        # Perform claim
        now = time.time()
        if best.broadcast:
            agents.set_status(agent_id, "busy", best.task_id)
            emit_event("task_claim", agent.name, f"{agent.name} 参与广播: {best.title}",
                       {"task_id": best.task_id, "claimed_by": agent_id, "agent_name": agent.name})
        else:
            if best.max_rounds > 0 and agent_id not in best.speaker_queue:
                best.speaker_queue.append(agent_id)
            tasks.update(best.task_id, status="claimed", claimed_by=agent_id, claimed_at=now,
                         speaker_queue=best.speaker_queue)
            agents.set_status(agent_id, "busy", best.task_id)
            emit_event("task_claim", agent.name, f"{agent.name} 领取了任务: {best.title}",
                       {"task_id": best.task_id, "claimed_by": agent_id, "agent_name": agent.name})

        result = {"ok": True, "claimed": tasks.find(best.task_id).to_dict()}
        if best.context:
            result["context_results"] = [
                {"task_id": d, "title": (dt.title if (dt := tasks.find(d)) else "?"),
                 "result": (dt.result if dt else None)}
                for d in best.context
            ]
        if best.max_rounds > 0:
            result["round"] = best.current_round + 1
            result["max_rounds"] = best.max_rounds
        self._json(200, result)

# ── WebSocket Server ─────────────────────────────────────────────

async def ws_handler(websocket):
    client_id = str(uuid.uuid4().hex[:8])
    ws_clients[client_id] = websocket
    try:
        await websocket.send(json.dumps({
            "type": "connected", "client_id": client_id,
            "agents": [a.to_dict() for a in agents.all()],
            "tasks": [t.to_dict() for t in tasks.all()],
        }, ensure_ascii=False))
        async for raw_msg in websocket:
            try:
                msg = json.loads(raw_msg)
                if msg.get("type") == "ping":
                    await websocket.send(json.dumps({"type": "pong"}))
                elif msg.get("type") == "chat":
                    emit_event("chat", msg.get("sender", "?"), msg.get("content", ""))
            except json.JSONDecodeError:
                pass
    except Exception:
        pass
    finally:
        ws_clients.pop(client_id, None)

async def ws_main():
    global _ws_event_loop
    _ws_event_loop = asyncio.get_event_loop()
    print(f" WebSocket server: ws://localhost:{WS_PORT}")
    async with serve(ws_handler, "0.0.0.0", WS_PORT) as server:
        await server.serve_forever()

def run_ws():
    asyncio.run(ws_main())

# ── HTTP main ────────────────────────────────────────────────────

def run_http():
    for p in ["messages.json", "agents.json", "tasks.json"]:
        path = os.path.join(BASE_DIR, p)
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                json.dump([], f)

    server = HTTPServer(("0.0.0.0", PORT), ChatHTTPHandler)
    print(f" HTTP REST API:  http://localhost:{PORT}")
    print(f"   /api/health  /api/tasks  /api/agents  /api/messages")
    print(f" Agent Identity | Task State Machine | GroupChat | Broadcast | HITL")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()

if __name__ == "__main__":
    # Start WebSocket in background thread, HTTP in main thread
    ws_thread = threading.Thread(target=run_ws, daemon=True)
    ws_thread.start()
    run_http()


# ── Task action handlers ─────────────────────────────────────────

def handle_task_action(task_id, action, body_bytes):
    data = _parse_body(body_bytes)
    if data is None:
        return _json_response(400, {"ok": False, "error": "Invalid JSON"})

    task = tasks.find(task_id)
    if not task:
        return _json_response(404, {"ok": False, "error": "Task not found"})

    agent_id = data.get("agent_id", "")
    agent = agents.find(agent_id)
    agent_name = agent.name if agent else agent_id
    now = time.time()

    if action == "claim":
        return _do_claim(task, agent_id, agent_name, now)
    elif action == "complete":
        return _do_complete(task, agent_id, agent_name, data.get("result", ""), now)
    elif action == "fail":
        return _do_fail(task, agent_id, agent_name, data.get("error", "Unknown error"), now)
    elif action == "cancel":
        return _do_cancel(task, now)
    elif action == "comment":
        content = data.get("content", "")
        if not content.strip():
            return _json_response(400, {"ok": False, "error": "content required"})
        emit_event("task_comment", data.get("sender", "?"), content,
                   {"task_id": task_id})
        return _json_response(200, {"ok": True})
    elif action == "approve":
        return _do_approve(task, agent_name, data.get("approved", True), now)

    return _json_response(400, {"ok": False, "error": f"Unknown action: {action}"})


def _can_claim(task, capabilities):
    """Check if an agent with given capabilities can claim this task."""
    required = set(task.required_capabilities)
    return required.issubset(set(capabilities))


def _do_claim(task, agent_id, agent_name, now):
    if task.status not in ("pending", "input_required"):
        return _json_response(400, {"ok": False, "error": f"Task is {task.status}, not claimable"})

    # For broadcast, don't change global status
    if task.broadcast:
        agents.set_status(agent_id, "busy", task.task_id)
        emit_event("task_claim", agent_name,
            f"{agent_name} 参与广播: {task.title}",
            {"task_id": task.task_id, "claimed_by": agent_id, "agent_name": agent_name})
        return _json_response(200, {"ok": True, "task": task.to_dict()})

    # For GroupChat, add to speaker queue
    if task.max_rounds > 0:
        if agent_id not in task.speaker_queue:
            task.speaker_queue.append(agent_id)
        tasks.update(task.task_id, speaker_queue=task.speaker_queue)

    # Normal claim
    tasks.update(task.task_id, status="claimed", claimed_by=agent_id, claimed_at=now)
    agents.set_status(agent_id, "busy", task.task_id)
    emit_event("task_claim", agent_name,
        f"{agent_name} 领取了任务: {task.title}",
        {"task_id": task.task_id, "claimed_by": agent_id, "agent_name": agent_name})
    return _json_response(200, {"ok": True, "task": tasks.find(task.task_id).to_dict()})


def _do_complete(task, agent_id, agent_name, result, now):
    # Broadcast: append to responses, keep open
    if task.broadcast:
        responses = list(task.responses)
        existing = [r for r in responses if (r.agent_id if hasattr(r, 'agent_id') else r.get('agent_id')) == agent_id]
        if existing:
            if hasattr(existing[0], 'result'):
                existing[0].result = result
                existing[0].completed_at = now
            else:
                existing[0]['result'] = result
                existing[0]['completed_at'] = now
        else:
            from models import TaskResponse
            responses.append(TaskResponse(agent_id=agent_id, agent_name=agent_name,
                                          result=result, completed_at=now))
        tasks.update(task.task_id, responses=responses)
        agents.set_status(agent_id, "online", None)
        n = len(responses)
        emit_event("broadcast_response", agent_name,
            f"📢 {agent_name} 回复了「{task.title}」：\n{result}",
            {"task_id": task.task_id, "agent_name": agent_name,
             "result": result, "broadcast": True, "response_count": n,
             "title": task.title})
        return _json_response(200, {"ok": True, "task": tasks.find(task.task_id).to_dict()})

    # Approval required: mark for review, don't complete yet
    if task.approval_required and not task.approved:
        tasks.update(task.task_id, status="input_required", result=result,
                     completed_by=agent_id, completed_at=now)
        agents.set_status(agent_id, "online", None)
        emit_event("approval_request", agent_name,
            f"{agent_name} 提交了结果，等待审批: {task.title}",
            {"task_id": task.task_id, "agent_name": agent_name, "result": result})
        return _json_response(200, {"ok": True, "task": tasks.find(task.task_id).to_dict(),
                                    "note": "Approval required"})

    # Normal completion
    if task.status not in ("claimed", "working", "input_required"):
        return _json_response(400, {"ok": False, "error": f"Task is {task.status}, cannot complete"})

    tasks.update(task.task_id, status="completed", result=result,
                 completed_by=agent_id, completed_at=now)
    agents.set_status(agent_id, "online", None)
    emit_event("task_complete", agent_name,
        f"[完成] {task.title}",
        {"task_id": task.task_id, "completed_by": agent_id,
         "agent_name": agent_name, "result": result})
    return _json_response(200, {"ok": True, "task": tasks.find(task.task_id).to_dict()})


def _do_fail(task, agent_id, agent_name, error, now):
    if task.broadcast:
        agents.set_status(agent_id, "online", None)
        return _json_response(200, {"ok": True, "task": task.to_dict()})
    if task.status not in ("claimed", "working"):
        return _json_response(400, {"ok": False, "error": f"Task is {task.status}, cannot fail"})
    tasks.update(task.task_id, status="failed", error=error)
    agents.set_status(agent_id, "online", None)
    emit_event("task_fail", agent_name,
        f"[失败] {task.title}",
        {"task_id": task.task_id, "failed_by": agent_id, "agent_name": agent_name, "error": error})
    return _json_response(200, {"ok": True, "task": tasks.find(task.task_id).to_dict()})


def _do_cancel(task, now):
    if task.status in TERMINAL_STATES:
        return _json_response(400, {"ok": False, "error": f"Task already {task.status}"})
    tasks.update(task.task_id, status="cancelled")
    emit_event("task_cancel", "System",
        f"[取消] 任务已取消: {task.title}",
        {"task_id": task.task_id})
    return _json_response(200, {"ok": True, "task": tasks.find(task.task_id).to_dict()})


def _do_approve(task, approver_name, approved, now):
    if not task.approval_required:
        return _json_response(400, {"ok": False, "error": "Task does not require approval"})
    if task.status != "input_required":
        return _json_response(400, {"ok": False, "error": f"Task is {task.status}, not awaiting approval"})
    if approved:
        tasks.update(task.task_id, status="completed", approved=True)
        emit_event("task_complete", approver_name,
            f"[审批通过] {task.title}",
            {"task_id": task.task_id, "approved_by": approver_name, "result": task.result})
    else:
        tasks.update(task.task_id, status="pending", result=None, completed_by=None, approved=False)
        emit_event("task_fail", approver_name,
            f"[审批拒绝] {task.title} — 已退回",
            {"task_id": task.task_id, "rejected_by": approver_name})
    return _json_response(200, {"ok": True, "task": tasks.find(task.task_id).to_dict()})


def handle_auto_claim(body_bytes):
    data = _parse_body(body_bytes)
    if data is None:
        return _json_response(400, {"ok": False, "error": "Invalid JSON"})
    agent_id = data.get("agent_id", "")
    capabilities = data.get("capabilities", [])

    agent = agents.find(agent_id)
    if not agent:
        return _json_response(400, {"ok": False, "error": "Agent not registered"})
    if agent.status == "offline":
        return _json_response(400, {"ok": False, "error": "Agent is offline"})

    agents.heartbeat(agent_id)
    all_tasks = tasks.all()
    priority_order = {"high": 0, "normal": 1, "low": 2}
    matching = []

    for t in all_tasks:
        if not _can_claim(t, capabilities):
            continue
        # Check context dependencies (all must be completed)
        if t.context:
            deps_done = all(
                (dt := tasks.find(dep_id)) and dt.status == "completed"
                for dep_id in t.context
            )
            if not deps_done:
                continue

        if t.status == "pending":
            if t.broadcast:
                existing_ids = [r.agent_id if hasattr(r, 'agent_id') else r.get('agent_id')
                               for r in t.responses]
                if agent_id not in existing_ids:
                    matching.append(t)
            elif t.max_rounds > 0:
                # GroupChat: add if not at max rounds
                if t.current_round < t.max_rounds:
                    matching.append(t)
            else:
                matching.append(t)
        elif t.status == "input_required" and t.claimed_by == agent_id and not t.approval_required:
            # Agent can continue working on input-required task
            matching.append(t)
        elif t.broadcast and t.status in ("claimed",):
            existing_ids = [r.agent_id if hasattr(r, 'agent_id') else r.get('agent_id')
                           for r in t.responses]
            if agent_id not in existing_ids:
                matching.append(t)

    matching.sort(key=lambda t: (priority_order.get(t.priority, 1), t.created_at))
    if not matching:
        return _json_response(200, {"ok": True, "claimed": None})

    best = matching[0]
    # For GroupChat, use speaker order
    if best.max_rounds > 0 and best.speaker_queue:
        # Next speaker is the one whose turn it is
        next_idx = best.current_round % len(best.speaker_queue)
        expected_speaker = best.speaker_queue[next_idx]
        if agent_id != expected_speaker:
            # Not this agent's turn yet
            return _json_response(200, {"ok": True, "claimed": None,
                                        "note": f"Waiting for speaker {expected_speaker}"})

    # Perform claim
    _, headers, body_bytes = _do_claim(best, agent_id, agent.name, time.time())
    result = json.loads(body_bytes.decode("utf-8"))
    # Add context info for the agent
    if best.context:
        context_tasks = []
        for dep_id in best.context:
            dt = tasks.find(dep_id)
            if dt:
                context_tasks.append({"task_id": dt.task_id, "title": dt.title, "result": dt.result})
        result["context_results"] = context_tasks
    if best.max_rounds > 0:
        result["round"] = best.current_round + 1
        result["max_rounds"] = best.max_rounds
    return _json_response(200, result)


def handle_input_response(task_id, body_bytes):
    """Agent responds to input-required clarification."""
    data = _parse_body(body_bytes)
    if data is None:
        return _json_response(400, {"ok": False, "error": "Invalid JSON"})
    task = tasks.find(task_id)
    if not task:
        return _json_response(404, {"ok": False, "error": "Task not found"})
    if task.status != "input_required":
        return _json_response(400, {"ok": False, "error": f"Task is {task.status}"})

    agent_id = data.get("agent_id", "")
    agent = agents.find(agent_id)
    agent_name = agent.name if agent else agent_id
    response = data.get("response", "")

    tasks.update(task.task_id, status="working")
    emit_event("task_comment", agent_name,
        f"[澄清] {agent_name}: {response}",
        {"task_id": task_id})
    return _json_response(200, {"ok": True, "task": tasks.find(task.task_id).to_dict()})


def handle_next_speaker(task_id, body_bytes):
    """Advance GroupChat to next speaker."""
    task = tasks.find(task_id)
    if not task:
        return _json_response(404, {"ok": False, "error": "Task not found"})
    if task.max_rounds <= 0:
        return _json_response(400, {"ok": False, "error": "Not a GroupChat task"})

    task.current_round += 1
    if task.current_round >= task.max_rounds:
        tasks.update(task.task_id, status="completed", current_round=task.current_round)
        emit_event("task_complete", "System",
            f"[群聊结束] {task.title} — 已完成 {task.max_rounds} 轮",
            {"task_id": task_id})
    else:
        tasks.update(task.task_id, current_round=task.current_round)

    return _json_response(200, {"ok": True, "task": tasks.find(task.task_id).to_dict()})


# ── WebSocket handler ────────────────────────────────────────────

async def ws_handler(websocket):
    """Handle WebSocket connection."""
    client_id = str(uuid.uuid4().hex[:8])
    ws_clients[client_id] = websocket
    try:
        # Send initial state
        await websocket.send(json.dumps({
            "type": "connected",
            "client_id": client_id,
            "agents": [a.to_dict() for a in agents.all()],
            "tasks": [t.to_dict() for t in tasks.all()],
        }, ensure_ascii=False))

        # Keep connection alive, handle client messages
        async for raw_msg in websocket:
            try:
                msg = json.loads(raw_msg)
                msg_type = msg.get("type", "")
                if msg_type == "ping":
                    await websocket.send(json.dumps({"type": "pong"}))
                elif msg_type == "chat":
                    emit_event("chat", msg.get("sender", "?"), msg.get("content", ""))
            except json.JSONDecodeError:
                pass
    except Exception:
        pass
    finally:
        ws_clients.pop(client_id, None)


# ── HTTP handler (for websockets process_request hook) ───────────

async def http_handler(connection, request):
    """Handle HTTP requests alongside WebSocket on the same port."""
    path = urlparse(request.path).path
    query = parse_qs(urlparse(request.path).query)

    if path == "/ws":
        return None  # Allow WebSocket upgrade

    # Read body
    body_bytes = b""
    if request.body:
        body_bytes = request.body

    status, headers, body = handle_http(path, request.method, query, body_bytes)
    # For HTTP, respond directly and don't upgrade
    await connection.respond(status, body.decode("utf-8", errors="replace"), headers)
    # Returning None after respond() means connection is already handled
    return None


# ── Main ─────────────────────────────────────────────────────────

async def main():
    # Ensure data files exist
    for path in [os.path.join(BASE_DIR, f) for f in
                 ["messages.json", "agents.json", "tasks.json"]]:
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                json.dump([], f)

    print(f" A2A Chat Platform v2  ws://localhost:{PORT}")
    print(f"   /api/health  /api/tasks  /api/agents  /ws")
    print(f"   Agent Identity  |  Task State Machine  |  GroupChat  |  Broadcast  |  HITL")

    async with serve(
        ws_handler,
        host="0.0.0.0",
        port=PORT,
        process_request=http_handler,
    ) as server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer stopped.")
