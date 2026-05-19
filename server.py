"""
Agent-to-Agent Chat Platform - Server
Observable A2A communication hub. Agents register capabilities, create tasks,
claim matching tasks, and report results — all visible in the chat UI.
Usage: python server.py [--port 8765]
"""
import json, time, os, sys, uuid, re
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

BASE_DIR = os.path.dirname(__file__)
MESSAGES_FILE = os.path.join(BASE_DIR, "messages.json")
AGENTS_FILE = os.path.join(BASE_DIR, "agents.json")
TASKS_FILE = os.path.join(BASE_DIR, "tasks.json")
MAX_MESSAGES = 500
AGENT_TIMEOUT = 60
PORT = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[1] == "--port" else 8765
SVR_STARTED = time.time()

# ── Data store helpers ──────────────────────────────────────────────

def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_messages():
    return load_json(MESSAGES_FILE, [])

def save_messages(msgs):
    save_json(MESSAGES_FILE, msgs[-MAX_MESSAGES:])

def append_message(msg):
    msgs = load_messages()
    msgs.append(msg)
    save_messages(msgs)

def load_agents():
    return load_json(AGENTS_FILE, [])

def save_agents(agents):
    save_json(AGENTS_FILE, agents)

def load_tasks():
    return load_json(TASKS_FILE, [])

def save_tasks(tasks):
    save_json(TASKS_FILE, tasks)

# ── Event helper ────────────────────────────────────────────────────

def append_event(event_type, sender, content, meta=None):
    msg = {"ts": time.time(), "type": event_type, "sender": sender, "content": content}
    if meta is not None:
        msg["meta"] = meta
    append_message(msg)
    return msg

# ── Agent helpers ───────────────────────────────────────────────────

def find_agent(agent_id):
    agents = load_agents()
    for a in agents:
        if a["agent_id"] == agent_id:
            return a
    return None

def update_agent(agent_id, updates):
    agents = load_agents()
    for a in agents:
        if a["agent_id"] == agent_id:
            a.update(updates)
            save_agents(agents)
            return a
    return None

def register_agent(agent_id, name, capabilities):
    agents = load_agents()
    now = time.time()
    for a in agents:
        if a["agent_id"] == agent_id:
            if a["name"] != name:
                return None
            a["name"] = name
            a["capabilities"] = capabilities
            a["status"] = "online"
            a["last_seen"] = now
            save_agents(agents)
            return a
    agent = {
        "agent_id": agent_id, "name": name,
        "capabilities": capabilities, "status": "online",
        "registered_at": now, "last_seen": now, "current_task_id": None
    }
    agents.append(agent)
    save_agents(agents)
    return agent

def unregister_agent(agent_id):
    agent = update_agent(agent_id, {"status": "offline", "last_seen": time.time()})
    if agent:
        release_agent_tasks(agent_id)
    return agent

def release_agent_tasks(agent_id):
    tasks = load_tasks()
    changed = False
    for t in tasks:
        if t["claimed_by"] == agent_id and t["status"] == "claimed":
            t["status"] = "pending"
            t["claimed_by"] = None
            t["claimed_at"] = None
            changed = True
    if changed:
        save_tasks(tasks)

def heartbeat_agent(agent_id):
    return update_agent(agent_id, {"last_seen": time.time(), "status": "online"})

def check_offline_agents():
    agents = load_agents()
    now = time.time()
    changed = False
    for a in agents:
        if a["status"] != "offline" and (now - a["last_seen"]) > AGENT_TIMEOUT:
            a["status"] = "offline"
            changed = True
    if changed:
        save_agents(agents)
        for a in agents:
            if a["status"] == "offline":
                release_agent_tasks(a["agent_id"])

# ── Task helpers ────────────────────────────────────────────────────

def next_task_id():
    return f"task-{uuid.uuid4().hex[:8]}"

def has_capabilities(agent_caps, required_caps):
    return set(required_caps).issubset(set(agent_caps))

def create_task(title, description, required_capabilities, priority, creator):
    tasks = load_tasks()
    task = {
        "task_id": next_task_id(), "status": "pending",
        "title": title, "description": description, "creator": creator,
        "required_capabilities": required_capabilities,
        "priority": priority if priority in ("high", "normal", "low") else "normal",
        "created_at": time.time(),
        "claimed_by": None, "claimed_at": None,
        "completed_by": None, "completed_at": None,
        "result": None, "error": None
    }
    tasks.append(task)
    save_tasks(tasks)
    return task

def find_task(task_id):
    for t in load_tasks():
        if t["task_id"] == task_id:
            return t
    return None

def update_task(task_id, updates):
    tasks = load_tasks()
    for t in tasks:
        if t["task_id"] == task_id:
            t.update(updates)
            save_tasks(tasks)
            return t
    return None

def claim_task(task_id, agent_id):
    check_offline_agents()
    task = find_task(task_id)
    if not task:
        return None, "Task not found"
    if task["status"] != "pending":
        return None, f"Task is {task['status']}, not pending"
    agent = find_agent(agent_id)
    if not agent:
        return None, "Agent not registered — use POST /api/agents/register first"
    if agent["status"] == "offline":
        return None, "Agent is offline — send heartbeat first"
    if not has_capabilities(agent["capabilities"], task["required_capabilities"]):
        missing = set(task["required_capabilities"]) - set(agent["capabilities"])
        return None, f"Agent lacks capabilities: {list(missing)}"
    now = time.time()
    update_task(task_id, {"status": "claimed", "claimed_by": agent_id, "claimed_at": now})
    update_agent(agent_id, {"status": "busy", "current_task_id": task_id})
    return find_task(task_id), None

def complete_task(task_id, agent_id, result):
    task = find_task(task_id)
    if not task:
        return None, "Task not found"
    if task["claimed_by"] != agent_id:
        return None, "Task not claimed by this agent"
    if task["status"] not in ("claimed", "in_progress"):
        return None, f"Task is {task['status']}, expected claimed or in_progress"
    now = time.time()
    update_task(task_id, {"status": "completed", "result": result, "completed_by": agent_id, "completed_at": now})
    update_agent(agent_id, {"status": "online", "current_task_id": None})
    return find_task(task_id), None

def fail_task(task_id, agent_id, error):
    task = find_task(task_id)
    if not task:
        return None, "Task not found"
    if task["claimed_by"] != agent_id:
        return None, "Task not claimed by this agent"
    if task["status"] not in ("claimed", "in_progress"):
        return None, f"Task is {task['status']}, expected claimed or in_progress"
    update_task(task_id, {"status": "failed", "error": error})
    update_agent(agent_id, {"status": "online", "current_task_id": None})
    return find_task(task_id), None

def cancel_task(task_id):
    task = find_task(task_id)
    if not task:
        return None, "Task not found"
    if task["status"] not in ("pending", "claimed"):
        return None, f"Cannot cancel task with status {task['status']}"
    if task["status"] == "claimed" and task["claimed_by"]:
        update_agent(task["claimed_by"], {"status": "online", "current_task_id": None})
    update_task(task_id, {"status": "cancelled"})
    return find_task(task_id), None

def auto_claim_task(agent_id, capabilities):
    check_offline_agents()
    agent = find_agent(agent_id)
    if not agent:
        return None, "Agent not registered"
    if agent["status"] == "offline":
        return None, "Agent is offline"
    update_agent(agent_id, {"last_seen": time.time()})
    tasks = load_tasks()
    priority_order = {"high": 0, "normal": 1, "low": 2}
    matching = [t for t in tasks if t["status"] == "pending" and has_capabilities(capabilities, t["required_capabilities"])]
    matching.sort(key=lambda t: (priority_order.get(t["priority"], 1), t["created_at"]))
    if not matching:
        return None, None
    task = matching[0]
    claimed, err = claim_task(task["task_id"], agent_id)
    if err:
        return None, err
    return claimed, None

def get_task_timeline(task_id):
    """Return all messages related to a task, ordered by time."""
    msgs = load_messages()
    related = []
    for m in msgs:
        meta = m.get("meta", {})
        if isinstance(meta, dict) and meta.get("task_id") == task_id:
            related.append(m)
        elif m.get("type", "").startswith("task_") and task_id in str(m.get("content", "")):
            # fallback: check content too
            pass
    related.sort(key=lambda m: m.get("ts", 0))
    return related


# ── Request handler ─────────────────────────────────────────────────

class ChatServer(BaseHTTPRequestHandler):

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json_response(self, code, data):
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _parse_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        body = self.rfile.read(length)
        try:
            return json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    def _serve_html(self):
        html_file = os.path.join(BASE_DIR, "index.html")
        with open(html_file, "r", encoding="utf-8") as f:
            html = f.read()
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def send_error(self, code, message=None):
        """Override: return JSON for API paths, HTML for others."""
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            self._json_response(code, {"ok": False, "error": message or str(code)})
        else:
            super().send_error(code, message)

    # ── Routing ─────────────────────────────────────────────────

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        qs = parse_qs(urlparse(self.path).query)

        if path == "/" or path == "":
            self._serve_html()
        elif path == "/api/messages":
            self._get_messages(qs.get("since", [None])[0])
        elif path == "/api/health":
            self._health()
        elif path == "/api/agents":
            self._get_agents(qs.get("status", [None])[0])
        elif path == "/api/tasks":
            self._get_tasks(qs.get("status", [None])[0])
        elif path.startswith("/api/tasks/") and path.count("/") == 3:
            self._get_task(path.split("/")[-1])
        elif path.startswith("/api/tasks/") and path.endswith("/timeline") and path.count("/") == 4:
            task_id = path.split("/")[-2]
            self._get_task_timeline(task_id)
        else:
            self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path
        action_match = re.match(r"^/api/tasks/([^/]+)/(claim|complete|fail|cancel|comment)$", path)

        if path == "/api/send":
            self._send_message()
        elif path == "/api/agents/register":
            self._agent_register()
        elif path == "/api/agents/unregister":
            self._agent_unregister()
        elif path == "/api/agents/heartbeat":
            self._agent_heartbeat()
        elif path == "/api/tasks":
            self._create_task()
        elif path == "/api/tasks/auto-claim":
            self._auto_claim()
        elif action_match:
            task_id = action_match.group(1)
            action = action_match.group(2)
            {"claim": self._task_claim, "complete": self._task_complete,
             "fail": self._task_fail, "cancel": self._task_cancel,
             "comment": self._task_comment}[action](task_id)
        elif path == "/api/notify":
            self._notify_legacy()
        else:
            self.send_error(404)

    # ── Health ──────────────────────────────────────────────────

    def _health(self):
        agents = load_agents()
        tasks = load_tasks()
        online = sum(1 for a in agents if a.get("status") != "offline")
        pending = sum(1 for t in tasks if t.get("status") == "pending")
        self._json_response(200, {
            "ok": True,
            "agents_online": online,
            "agents_total": len(agents),
            "tasks_pending": pending,
            "tasks_total": len(tasks),
            "uptime": round(time.time() - SVR_STARTED, 1)
        })

    # ── Messages ────────────────────────────────────────────────

    def _get_messages(self, since=None):
        msgs = load_messages()
        if since:
            try:
                since_ts = float(since)
                msgs = [m for m in msgs if m.get("ts", 0) > since_ts]
            except ValueError:
                pass
        self._json_response(200, msgs)

    def _send_message(self):
        data = self._parse_body()
        if data is None:
            self._json_response(400, {"ok": False, "error": "Invalid JSON body"})
            return
        sender = data.get("sender", "Anonymous")
        content = data.get("content", "")
        msg = append_event("chat", sender, content)
        self._json_response(200, {"ok": True, "msg": msg})

    # ── Agents ──────────────────────────────────────────────────

    def _agent_register(self):
        data = self._parse_body()
        if data is None:
            self._json_response(400, {"ok": False, "error": "Invalid JSON body"})
            return
        agent_id = data.get("agent_id", "")
        name = data.get("name", "Unknown")
        capabilities = data.get("capabilities", [])
        if not isinstance(capabilities, list):
            self._json_response(400, {"ok": False, "error": "capabilities must be a list"})
            return
        if not agent_id:
            agent_id = f"{name}-{uuid.uuid4().hex[:6]}"
        agent = register_agent(agent_id, name, capabilities)
        if agent is None:
            self._json_response(409, {"ok": False, "error": "agent_id already used with different name"})
            return
        caps_str = ", ".join(capabilities) if capabilities else "no capabilities"
        append_event("agent_register", name,
            f"{name} 上线 — 能力: {caps_str}",
            {"agent_id": agent_id, "capabilities": capabilities})
        self._json_response(200, {"ok": True, "agent": agent})

    def _agent_unregister(self):
        data = self._parse_body()
        if data is None:
            self._json_response(400, {"ok": False, "error": "Invalid JSON body"})
            return
        agent_id = data.get("agent_id", "")
        agent = find_agent(agent_id)
        if not agent:
            self._json_response(404, {"ok": False, "error": "Agent not found"})
            return
        unregister_agent(agent_id)
        append_event("agent_offline", agent["name"],
            f"{agent['name']} 离线了", {"agent_id": agent_id})
        self._json_response(200, {"ok": True})

    def _agent_heartbeat(self):
        data = self._parse_body()
        if data is None:
            self._json_response(400, {"ok": False, "error": "Invalid JSON body"})
            return
        agent_id = data.get("agent_id", "")
        if heartbeat_agent(agent_id) is None:
            self._json_response(404, {"ok": False, "error": "Agent not found"})
        else:
            self._json_response(200, {"ok": True})

    def _get_agents(self, status=None):
        agents = load_agents()
        if status:
            agents = [a for a in agents if a.get("status") == status]
        self._json_response(200, agents)

    # ── Tasks ───────────────────────────────────────────────────

    def _create_task(self):
        data = self._parse_body()
        if data is None:
            self._json_response(400, {"ok": False, "error": "Invalid JSON body"})
            return
        title = data.get("title", "Untitled Task")
        description = data.get("description", "")
        required_capabilities = data.get("required_capabilities", [])
        if not isinstance(required_capabilities, list):
            self._json_response(400, {"ok": False, "error": "required_capabilities must be a list"})
            return
        priority = data.get("priority", "normal")
        creator = data.get("creator", "Anonymous")
        task = create_task(title, description, required_capabilities, priority, creator)
        append_event("task_create", creator,
            f"[新任务] {title}",
            {"task_id": task["task_id"], "title": title, "description": description,
             "required_capabilities": required_capabilities, "priority": priority})
        self._json_response(200, {"ok": True, "task": task})

    def _get_tasks(self, status=None):
        tasks = load_tasks()
        if status:
            tasks = [t for t in tasks if t.get("status") == status]
        self._json_response(200, tasks)

    def _get_task(self, task_id):
        task = find_task(task_id)
        if task is None:
            self._json_response(404, {"ok": False, "error": "Task not found"})
        else:
            self._json_response(200, task)

    def _get_task_timeline(self, task_id):
        task = find_task(task_id)
        if task is None:
            self._json_response(404, {"ok": False, "error": "Task not found"})
            return
        timeline = get_task_timeline(task_id)
        self._json_response(200, {"task": task, "timeline": timeline})

    def _task_claim(self, task_id):
        data = self._parse_body()
        if data is None:
            self._json_response(400, {"ok": False, "error": "Invalid JSON body"})
            return
        agent_id = data.get("agent_id", "")
        task, error = claim_task(task_id, agent_id)
        if error:
            self._json_response(400, {"ok": False, "error": error})
            return
        agent = find_agent(agent_id)
        agent_name = agent["name"] if agent else agent_id
        append_event("task_claim", agent_name,
            f"{agent_name} 领取了任务: {task['title']}",
            {"task_id": task_id, "claimed_by": agent_id, "agent_name": agent_name})
        self._json_response(200, {"ok": True, "task": task})

    def _task_complete(self, task_id):
        data = self._parse_body()
        if data is None:
            self._json_response(400, {"ok": False, "error": "Invalid JSON body"})
            return
        agent_id = data.get("agent_id", "")
        result = data.get("result", "")
        task, error = complete_task(task_id, agent_id, result)
        if error:
            self._json_response(400, {"ok": False, "error": error})
            return
        agent = find_agent(agent_id)
        agent_name = agent["name"] if agent else agent_id
        append_event("task_complete", agent_name,
            f"[完成] {task['title']}",
            {"task_id": task_id, "completed_by": agent_id, "agent_name": agent_name, "result": result})
        self._json_response(200, {"ok": True, "task": task})

    def _task_fail(self, task_id):
        data = self._parse_body()
        if data is None:
            self._json_response(400, {"ok": False, "error": "Invalid JSON body"})
            return
        agent_id = data.get("agent_id", "")
        error_msg = data.get("error", "Unknown error")
        task, error = fail_task(task_id, agent_id, error_msg)
        if error:
            self._json_response(400, {"ok": False, "error": error})
            return
        agent = find_agent(agent_id)
        agent_name = agent["name"] if agent else agent_id
        append_event("task_fail", agent_name,
            f"[失败] {task['title']}",
            {"task_id": task_id, "failed_by": agent_id, "agent_name": agent_name, "error": error_msg})
        self._json_response(200, {"ok": True, "task": task})

    def _task_cancel(self, task_id):
        task, error = cancel_task(task_id)
        if error:
            self._json_response(400, {"ok": False, "error": error})
            return
        append_event("task_cancel", "System",
            f"[取消] 任务已取消: {task['title']}",
            {"task_id": task_id})
        self._json_response(200, {"ok": True, "task": task})

    def _task_comment(self, task_id):
        data = self._parse_body()
        if data is None:
            self._json_response(400, {"ok": False, "error": "Invalid JSON body"})
            return
        task = find_task(task_id)
        if task is None:
            self._json_response(404, {"ok": False, "error": "Task not found"})
            return
        sender = data.get("sender", "Anonymous")
        content = data.get("content", "")
        if not content.strip():
            self._json_response(400, {"ok": False, "error": "content is required"})
            return
        append_event("task_comment", sender,
            f"[评论] {task['title']}: {content}",
            {"task_id": task_id, "comment": content})
        self._json_response(200, {"ok": True})

    def _auto_claim(self):
        data = self._parse_body()
        if data is None:
            self._json_response(400, {"ok": False, "error": "Invalid JSON body"})
            return
        agent_id = data.get("agent_id", "")
        capabilities = data.get("capabilities", [])
        task, error = auto_claim_task(agent_id, capabilities)
        if error:
            self._json_response(400, {"ok": False, "error": error})
            return
        if task is None:
            self._json_response(200, {"ok": True, "claimed": None})
            return
        agent = find_agent(agent_id)
        agent_name = agent["name"] if agent else agent_id
        append_event("task_claim", agent_name,
            f"{agent_name} 领取了任务: {task['title']}",
            {"task_id": task["task_id"], "claimed_by": agent_id, "agent_name": agent_name})
        self._json_response(200, {"ok": True, "claimed": task})

    # ── Legacy ──────────────────────────────────────────────────

    def _notify_legacy(self):
        data = self._parse_body()
        if data is None:
            self._json_response(400, {"ok": False, "error": "Invalid JSON body"})
            return
        agent_name = data.get("agent", data.get("name", "unknown"))
        capabilities = data.get("capabilities", [])
        agent_id = data.get("agent_id", f"legacy-{agent_name}")
        register_agent(agent_id, agent_name, capabilities)
        self._json_response(200, {"ok": True, "note": "deprecated, use /api/agents/register"})

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    if not os.path.exists(MESSAGES_FILE):
        save_messages([])
    if not os.path.exists(AGENTS_FILE):
        save_agents([])
    if not os.path.exists(TASKS_FILE):
        save_tasks([])

    server = HTTPServer(("0.0.0.0", PORT), ChatServer)
    print(f" A2A Chat Platform  http://localhost:{PORT}")
    print(f"   /api/health  /api/send  /api/tasks  /api/agents")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
        print("\nServer stopped.")
