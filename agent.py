"""
A2A Agent Client v2 — Identity + AI
Usage:
  python agent.py register --name Claude --role "Senior Code Reviewer" --goal "Find bugs" --backstory "15 years..." --capabilities code_review,file_edit --model deepseek/deepseek-v4-pro
  python agent.py auto --name Claude --role "..." --goal "..." --backstory "..." --capabilities code_review,file_edit --auto-reply --verbose
"""
import json, time, sys, os, uuid, urllib.request, urllib.error

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = os.path.dirname(__file__)
AGENT_ID_FILE = os.path.join(BASE_DIR, ".agent_id")
HOST = os.environ.get("CHAT_HOST", "http://localhost:8765")

# ── CLAUDE.md auto-discovery ───────────────────────────────────

def _find_claude_md():
    """Search for CLAUDE.md in common locations. Returns path or None."""
    candidates = [
        os.path.join(BASE_DIR, "CLAUDE.md"),
        os.path.join(os.path.dirname(BASE_DIR), "CLAUDE.md"),
        os.path.expanduser("~/.claude/CLAUDE.md"),
        "CLAUDE.md",
        "../CLAUDE.md",
    ]
    for p in candidates:
        try:
            if os.path.exists(p):
                return p
        except Exception:
            pass
    return None

def _parse_claude_md(path):
    """Extract A2A config and agent identity from CLAUDE.md."""
    config = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("#") or not line:
                continue
            # A2A Platform config
            for key in ["A2A_HOST", "A2A_WS", "AGENT_NAME", "AGENT_ROLE",
                         "AGENT_GOAL", "AGENT_BACKSTORY", "AGENT_CAPS", "AGENT_MODEL"]:
                if line.startswith(f"{key}=") or line.startswith(f"{key} ="):
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                    config[key.lower()] = val
    except Exception:
        pass
    return config

def _apply_claude_config(config, args):
    """Apply CLAUDE.md config as defaults; CLI args override."""
    global HOST
    if config.get("a2a_host") and not os.environ.get("CHAT_HOST"):
        HOST = config["a2a_host"]
    # Agent identity: CLI args win, then CLAUDE.md, then defaults
    if config.get("agent_name") and not getattr(args, 'name', None):
        args.name = config["agent_name"]
    if config.get("agent_role") and not getattr(args, 'role', ''):
        args.role = config["agent_role"]
    if config.get("agent_goal") and not getattr(args, 'goal', ''):
        args.goal = config["agent_goal"]
    if config.get("agent_backstory") and not getattr(args, 'backstory', ''):
        args.backstory = config["agent_backstory"]
    if config.get("agent_caps") and not getattr(args, 'capabilities', ''):
        args.capabilities = config["agent_caps"]
    if config.get("agent_model") and not getattr(args, 'model', ''):
        args.model = config["agent_model"]
WS_HOST = os.environ.get("CHAT_WS", "ws://localhost:8765/ws")

# ── HTTP helpers ────────────────────────────────────────────────

def api_get(path):
    url = f"{HOST}{path}"
    resp = urllib.request.urlopen(url)
    return json.loads(resp.read().decode("utf-8"))

def api_post(path, data):
    url = f"{HOST}{path}"
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body,
        headers={"Content-Type": "application/json; charset=utf-8"})
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

# ── AI Model config ─────────────────────────────────────────────

_AI_CONFIG = None

def _load_agent_prompt(agent_name):
    """Load system prompt from learning_agents.json for interview prep agents."""
    prompt_path = os.path.join(BASE_DIR, "learning_agents.json")
    if not os.path.exists(prompt_path):
        return None
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Check orchestrator
        if data.get("orchestrator", {}).get("name") == agent_name:
            return data["orchestrator"].get("system_prompt")
        # Check specialists
        for s in data.get("specialists", []):
            if s.get("name") == agent_name:
                return s.get("system_prompt")
    except Exception:
        pass
    return None

def _load_ai_config():
    global _AI_CONFIG
    if _AI_CONFIG is not None:
        return _AI_CONFIG
    _AI_CONFIG = {"api_key": None, "base_url": None, "model": None}
    for p in [
        os.path.expanduser("~/.openclaw/openclaw.json"),
        os.path.expanduser("~/.config/openclaw/openclaw.json"),
    ]:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                agents_cfg = cfg.get("agents", {}).get("defaults", {})
                model_str = agents_cfg.get("model", "")
                provider = model_str.split("/")[0] if "/" in model_str else "deepseek"
                model_id = model_str.split("/")[1] if "/" in model_str else model_str
                providers = cfg.get("models", {}).get("providers", {})
                if provider in providers:
                    pcfg = providers[provider]
                    _AI_CONFIG["base_url"] = pcfg.get("baseUrl", "")
                    _AI_CONFIG["api_key"] = pcfg.get("apiKey", "")
                    _AI_CONFIG["model"] = model_str
                break
            except Exception:
                pass
    for key in ["AI_API_KEY", "AI_BASE_URL", "AI_MODEL"]:
        env_key = key
        cfg_key = key.replace("AI_", "").lower()
        if os.environ.get(env_key):
            _AI_CONFIG[cfg_key] = os.environ[env_key]
    return _AI_CONFIG

def call_ai(task_title, task_desc, agent_name, role, goal, backstory, capabilities, context_results=None):
    """Call AI model to answer a task, using agent identity for personalization."""
    cfg = _load_ai_config()
    if not cfg["api_key"] or not cfg["base_url"]:
        return None, "No AI API configured"

    # Load system prompt from learning_agents.json if available
    system_prompt = _load_agent_prompt(agent_name)

    # Build rich identity-aware prompt (CrewAI-inspired)
    identity_block = f"""You are "{agent_name}", an AI agent with a specific identity:

ROLE: {role or f"AI assistant specialized in {', '.join(capabilities) if capabilities else 'general tasks'}"}
GOAL: {goal or "Provide helpful, accurate responses"}
BACKSTORY: {backstory or "You are a capable AI agent ready to help."}
CAPABILITIES: {', '.join(capabilities) if capabilities else 'general'}"""

    context_block = ""
    if context_results:
        ctx_parts = []
        for ctx in context_results:
            ctx_parts.append(f"- Task '{ctx.get('title', '?')}': {ctx.get('result', 'no result')[:200]}")
        context_block = "\n\nPREVIOUS TASK RESULTS (context chain):\n" + "\n".join(ctx_parts)

    prompt = f"""{identity_block}

TASK:
Title: {task_title}
Description: {task_desc or '(no description)'}
{context_block}

INSTRUCTIONS:
- Respond in character as {agent_name}, consistent with your role and backstory.
- If the task asks what model you use: state that you are powered by DeepSeek v4 Pro via API.
- Answer the task directly and helpfully.
- Keep your response concise and structured.
- If this is a status report, confirm you are operational and state your capabilities.
{SYSTEM_PROMPT_INJECT}"""

    # Inject system prompt from learning_agents.json if available
    if system_prompt:
        prompt = prompt.replace("{SYSTEM_PROMPT_INJECT}", f"\n\n## SYSTEM PROMPT\n{system_prompt}")
    else:
        prompt = prompt.replace("{SYSTEM_PROMPT_INJECT}", "")

    url = cfg["base_url"].rstrip("/") + "/v1/chat/completions"
    model_name = cfg["model"].split("/")[-1] if "/" in cfg["model"] else cfg["model"]
    body = json.dumps({
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1000,
        "temperature": 0.7,
    }).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {cfg['api_key']}",
    }
    try:
        req = urllib.request.Request(url, data=body, headers=headers)
        resp = urllib.request.urlopen(req, timeout=60)
        data = json.loads(resp.read().decode("utf-8"))
        msg = data["choices"][0]["message"]
        thinking = (msg.get("reasoning_content") or "").strip()
        answer = (msg.get("content") or "").strip()
        if not answer and thinking:
            answer = thinking; thinking = ""
        if not answer:
            return None, None, "AI returned empty response"
        return answer, thinking, None
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:200]
        return None, None, f"AI API error {e.code}: {err_body}"
    except Exception as e:
        return None, None, str(e)

# ── Helpers ─────────────────────────────────────────────────────

def _parse_caps(caps_str):
    if not caps_str:
        return []
    return [c.strip() for c in caps_str.split(",") if c.strip()]

def safe_print(msg):
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode("ascii"))

# ── Commands ────────────────────────────────────────────────────

def cmd_register(args):
    agent_id = f"{args.name}-{uuid.uuid4().hex[:6]}"
    existing = load_agent_id()
    if existing:
        parts = existing.rsplit("-", 1)
        if parts[0] == args.name:
            agent_id = existing
    save_agent_id(agent_id)
    caps = _parse_caps(args.capabilities) if args.capabilities else []
    result = api_post("/api/agents/register", {
        "agent_id": agent_id,
        "name": args.name,
        "role": args.role or "",
        "goal": args.goal or "",
        "backstory": args.backstory or "",
        "capabilities": caps,
        "model": args.model or "",
    })
    safe_print(f"[REGISTERED] {args.name} ({agent_id})")
    if args.role:
        safe_print(f"  Role: {args.role}")
    safe_print(f"  Capabilities: {', '.join(caps) if caps else 'none'}")
    return agent_id

def cmd_auto(args):
    # Auto-discover from CLAUDE.md
    cm_path = _find_claude_md()
    if cm_path:
        config = _parse_claude_md(cm_path)
        _apply_claude_config(config, args)
        safe_print(f"[DISCOVERY] Loaded config from {cm_path}")
        safe_print(f"  Platform: {HOST}")

    agent_id = load_agent_id()
    if not agent_id or agent_id.rsplit("-", 1)[0] != args.name:
        agent_id = f"{args.name}-{uuid.uuid4().hex[:6]}"
        save_agent_id(agent_id)
    caps = _parse_caps(args.capabilities) if args.capabilities else []
    interval = int(args.poll_interval) if args.poll_interval else 5
    verbose = args.verbose
    once = args.once
    auto_reply = args.auto_reply
    role = args.role or ""
    goal = args.goal or ""
    backstory = args.backstory or ""
    tick = 0

    # Register with identity
    api_post("/api/agents/register", {
        "agent_id": agent_id, "name": args.name,
        "role": role, "goal": goal, "backstory": backstory,
        "capabilities": caps, "model": args.model or "",
    })
    identity = role or args.name
    mode_str = "auto-reply" if auto_reply else "interactive"
    safe_print(f"[REGISTERED] {identity} ({agent_id})")
    safe_print(f"[AUTO:{mode_str}] Polling every {interval}s. Ctrl+C to stop.\n")

    running = True
    while running:
        try:
            api_post("/api/agents/heartbeat", {"agent_id": agent_id})
            tick += 1

            result = api_post("/api/tasks/auto-claim", {
                "agent_id": agent_id,
                "capabilities": caps,
            })
            if result.get("error"):
                safe_print(f"[AUTO] Error: {result['error']}")
            elif result.get("claimed"):
                task = result.get("claimed", result)
                context_results = result.get("context_results", [])
                round_info = f" [Round {result.get('round','?')}/{result.get('max_rounds','?')}]" if result.get("round") else ""

                safe_print(f"[AUTO] Claimed {task['task_id']}: \"{task['title']}\"{round_info}")
                safe_print(f"       Creator: {task.get('creator','?')}  |  Priority: {task.get('priority','normal')}")
                if task.get("broadcast"):
                    safe_print(f"       Mode: BROADCAST")
                if task.get("max_rounds", 0) > 0:
                    safe_print(f"       Mode: GROUPCHAT")
                if context_results:
                    safe_print(f"       Context: {len(context_results)} dependent tasks")

                # ── Progress: report to server that we're working ──
                api_post("/api/agents/progress", {
                    "agent_id": agent_id,
                    "task_id": task['task_id'],
                    "status": f"正在分析: {task['title'][:60]}"
                })

                # ── Observe other agents ──
                other_agents_info = ""
                if auto_reply:
                    try:
                        obs = api_post("/api/agents/observe", {"agent_id": agent_id, "since": time.time() - 60})
                        observed = obs.get("observed", [])
                        # Find other agents who already responded to this task
                        colleagues = set()
                        for m in observed:
                            meta = m.get("meta", {})
                            if meta.get("task_id") == task["task_id"] and meta.get("agent_name"):
                                name = meta["agent_name"]
                                if name != args.name:
                                    colleagues.add(name)
                        if colleagues:
                            colleagues_str = ", ".join(colleagues)
                            other_agents_info = f"\n\n[系统通知] 以下Agent已回复此任务: {colleagues_str}。请在回复中引用或回应他们的观点。"
                            safe_print(f"       Colleagues already responded: {colleagues_str}")
                    except Exception:
                        pass

                # Get result
                if auto_reply:
                    safe_print(f"       Calling AI model ({identity})...")
                    # Progress: AI thinking
                    api_post("/api/agents/progress", {
                        "agent_id": agent_id,
                        "task_id": task['task_id'],
                        "status": "AI推理中..."
                    })
                    answer, thinking, err = call_ai(
                        task["title"], task.get("description", "") + other_agents_info,
                        args.name, role, goal, backstory, caps,
                        context_results=context_results,
                    )
                    if err:
                        safe_print(f"       AI error: {err}")
                        result_text = f"[{args.name}] 收到任务但AI调用失败: {err}"
                    else:
                        if thinking:
                            safe_print(f"       Thinking: {thinking[:80]}...")
                            result_text = f"<!--thinking-->\n{thinking}\n<!--/thinking-->\n\n{answer}"
                        else:
                            result_text = answer
                        safe_print(f"       AI answer: {answer[:120]}...")
                else:
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
                    "result": result_text,
                })
                safe_print(f"[COMPLETED] {task['task_id']}: {task['title']}\n")
                if once:
                    running = False
            else:
                if verbose:
                    t = time.strftime("%H:%M:%S")
                    matching = _count_matching(caps)
                    safe_print(f"[AUTO] {t} tick#{tick} heartbeat ok, {matching} matching tasks")
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

    if not once:
        try:
            api_post("/api/agents/unregister", {"agent_id": agent_id})
            safe_print("[OFFLINE] Unregistered.")
        except Exception:
            pass
    safe_print("Bye.")

def cmd_create_task(args):
    caps = _parse_caps(args.capabilities) if args.capabilities else []
    context = _parse_caps(args.context) if args.context else []
    result = api_post("/api/tasks", {
        "title": args.title,
        "description": args.desc or "",
        "required_capabilities": caps,
        "priority": args.priority or "normal",
        "creator": args.creator or "Anonymous",
        "broadcast": args.broadcast,
        "context": context,
        "max_rounds": int(args.max_rounds) if args.max_rounds else 0,
        "approval_required": args.approval_required,
    })
    if result.get("ok"):
        task = result["task"]
        tags = []
        if task.get("broadcast"): tags.append("📢广播")
        if task.get("max_rounds"): tags.append(f"💬群聊{task['max_rounds']}轮")
        if task.get("approval_required"): tags.append("✋需审批")
        safe_print(f"[CREATED] {task['task_id']}: \"{task['title']}\" {' '.join(tags)}")
        safe_print(f"  Status: {task['status']}, Priority: {task.get('priority','normal')}")
    else:
        safe_print(f"[ERROR] {result.get('error', 'Unknown error')}")

def cmd_tasks(args):
    status = args.status or ""
    path = f"/api/tasks{'?status=' + status if status else ''}"
    tlist = api_get(path)
    if isinstance(tlist, dict):
        tlist = [tlist]
    if not tlist:
        safe_print("No tasks found.")
        return
    for t in tlist:
        icon = {"pending":"[PEND]","claimed":"[BUSY]","working":"[WORK]",
                "input_required":"[WAIT]","completed":"[DONE]","failed":"[FAIL]",
                "cancelled":"[CANC]"}.get(t["status"],"?")
        tags = []
        if t.get("broadcast"): tags.append("broadcast")
        if t.get("max_rounds"): tags.append(f"groupchat({t.get('current_round',0)}/{t['max_rounds']})")
        safe_print(f"  {icon} {t['task_id']} [{t['status']}] {t['title']} {' '.join(tags)}")
        if t.get("claimed_by"):
            safe_print(f"     Claimed by: {t['claimed_by']}")
        if t.get("result"):
            safe_print(f"     Result: {t['result'][:120]}")
        if t.get("responses"):
            safe_print(f"     Responses: {len(t['responses'])}")

def _count_matching(caps):
    try:
        tlist = api_get("/api/tasks?status=pending")
        if not isinstance(tlist, list):
            return 0
        return sum(1 for t in tlist
                   if set(t.get("required_capabilities", [])).issubset(set(caps)))
    except Exception:
        return 0

# Legacy commands (kept for compatibility)
def cmd_send(args):
    api_post("/api/send", {"sender": args.name, "content": args.msg})
    safe_print(f"[{args.name}] {args.msg}")

def cmd_read(args):
    path = "/api/messages"
    if args.since:
        path += f"?since={args.since}"
    msgs = api_get(path)
    for m in msgs[-20:]:
        t = time.strftime("%H:%M:%S", time.localtime(m.get("ts", 0)))
        safe_print(f"[{t}] {m.get('sender','?')}: {m.get('content','')}")

def cmd_listen(args):
    safe_print(f" Listening on {HOST}...")
    last_ts = time.time()
    while True:
        try:
            msgs = api_get(f"/api/messages?since={last_ts}")
            for m in msgs:
                t = time.strftime("%H:%M:%S", time.localtime(m.get("ts", 0)))
                safe_print(f"[{t}] {m.get('sender','?')}: {m.get('content','')}")
            if msgs:
                last_ts = max(m.get("ts", 0) for m in msgs)
        except Exception:
            pass
        time.sleep(1)


# ── Manager Mode ───────────────────────────────────────────────

def load_registry():
    """Load specialist registry from agent_registry.json."""
    for p in [os.path.join(BASE_DIR, "agent_registry.json"), "agent_registry.json"]:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
    return {"specialists": []}

def spawn_agent(name, caps, role, goal, backstory, poll_interval=10):
    """Wake up a specialist agent by launching its process."""
    import subprocess
    python = sys.executable
    args = [
        python, "-B", os.path.join(BASE_DIR, "agent.py"), "auto",
        "--name", name,
        "--role", role,
        "--goal", goal,
        "--backstory", backstory,
        "--capabilities", caps if isinstance(caps, str) else ",".join(caps),
        "--auto-reply", "--verbose",
        "--poll-interval", str(poll_interval),
    ]
    try:
        proc = subprocess.Popen(
            args, cwd=BASE_DIR,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        safe_print(f"[MANAGER] Waking up {name} (PID {proc.pid})...")
        return True, proc.pid
    except Exception as e:
        return False, str(e)
    """Load specialist registry from agent_registry.json."""
    for p in [os.path.join(BASE_DIR, "agent_registry.json"), "agent_registry.json"]:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
    return {"specialists": []}

def cmd_manager(args):
    """Manager agent: listens to user, dispatches tasks to specialists."""
    agent_id = load_agent_id()
    if not agent_id or agent_id.rsplit("-", 1)[0] != args.name:
        agent_id = f"{args.name}-{uuid.uuid4().hex[:6]}"
        save_agent_id(agent_id)

    registry = load_registry()
    interval = int(args.poll_interval) if args.poll_interval else 5
    role = args.role or "Agent Orchestrator"
    goal = args.goal or "Parse user intent and dispatch to specialists"
    backstory = args.backstory or ""
    caps = _parse_caps(args.capabilities) if args.capabilities else ["chat", "task_orchestration"]

    # Register
    api_post("/api/agents/register", {
        "agent_id": agent_id, "name": args.name,
        "role": role, "goal": goal, "backstory": backstory,
        "capabilities": caps, "model": args.model or "",
    })
    safe_print(f"[MANAGER] {args.name} online — {len(registry['specialists'])} specialists known")

    # Track what we've seen and dispatched
    last_msg_ts = time.time()
    dispatched_tasks = set()  # task_ids we created
    active_conversation = False

    safe_print(f"[MANAGER] Listening for user requests. Write in chat to begin.\n")

    running = True
    while running:
        try:
            api_post("/api/agents/heartbeat", {"agent_id": agent_id})

            # ── Observe new user messages ──
            observed = api_post("/api/agents/observe", {
                "agent_id": agent_id, "since": last_msg_ts
            })
            msgs = observed.get("observed", [])
            user_msgs = [m for m in msgs if m.get("type") == "chat"
                        and m.get("sender") not in (args.name, "System")]

            # ── Check dispatched tasks completion ──
            if dispatched_tasks:
                for tid in list(dispatched_tasks):
                    try:
                        t = api_get(f"/api/tasks/{tid}")
                        if isinstance(t, dict) and t.get("status") == "completed":
                            safe_print(f"[MANAGER] Task completed: {t['title']}")
                            dispatched_tasks.discard(tid)
                            # Summarize and report to user
                            result = (t.get("result") or "")[:500]
                            specialist = t.get("completed_by", "specialist")
                            api_post("/api/send", {
                                "sender": args.name,
                                "content": f"📋 {specialist} 完成了「{t['title']}」:\n{result}"
                            })
                    except Exception:
                        pass

            # ── Process user messages ──
            if user_msgs:
                safe_print(f"[MANAGER] {len(user_msgs)} new user message(s)")
                latest = user_msgs[-1]
                content = latest.get("content", "")
                sender = latest.get("sender", "User")
                last_msg_ts = max(m.get("ts", 0) for m in msgs) + 0.1

                # Let AI parse intent
                safe_print(f"[MANAGER] Parsing: {content[:80]}...")
                intent, _, err = call_ai(
                    "Parse user intent", content,
                    args.name,
                    "Agent Orchestrator & User Proxy",
                    "Parse natural language into structured task: determine what the user wants, which specialist(s) should handle it, and construct a task title and description.",
                    "You are the manager of a team of AI specialist agents. Your job is to understand user requests and dispatch them to the right specialist.",
                    caps,
                )

                if err:
                    api_post("/api/send", {
                        "sender": args.name,
                        "content": f"抱歉我暂时无法处理: {err}"
                    })
                    continue

                # Match to specialist
                specialists = registry.get("specialists", [])
                online_agents = []
                try:
                    online_agents = [a["name"] for a in api_get("/api/agents")
                                    if a.get("status") == "online"]
                except Exception:
                    pass

                matched = None
                for s in specialists:
                    if s["name"] in online_agents and s["name"] != args.name:
                        matched = s
                        break

                if matched:
                    # Check if specialist is online; if not, wake it up
                    if matched["name"] not in online_agents:
                        safe_print(f"[MANAGER] {matched['name']} is offline — waking up...")
                        api_post("/api/send", {
                            "sender": args.name,
                            "content": f"🔔 {matched['name']} 当前离线，正在唤醒..."
                        })
                        ok, pid = spawn_agent(
                            matched["name"],
                            matched.get("capabilities", []),
                            matched.get("role", ""),
                            matched.get("goal", ""),
                            matched.get("backstory", ""),
                        )
                        if ok:
                            api_post("/api/send", {
                                "sender": args.name,
                                "content": f"✅ {matched['name']} 已唤醒 (PID {pid})，稍等片刻即可接任务..."
                            })
                            time.sleep(8)  # Give it time to register
                        else:
                            api_post("/api/send", {
                                "sender": args.name,
                                "content": f"❌ 无法唤醒 {matched['name']}: {pid}"
                            })
                            continue

                    # Create task
                    task_title = f"{matched['name']}: {content[:60]}"
                    task_desc = content
                    result = api_post("/api/tasks", {
                        "title": task_title,
                        "description": task_desc,
                        "required_capabilities": matched.get("capabilities", []),
                        "priority": "high",
                        "creator": args.name,
                        "broadcast": False,
                    })
                    if result.get("ok"):
                        tid = result["task"]["task_id"]
                        dispatched_tasks.add(tid)
                        safe_print(f"[MANAGER] Dispatched → {matched['name']}: {task_title}")
                        api_post("/api/send", {
                            "sender": args.name,
                            "content": f"📋 已分派「{task_title}」给 {matched['name']}，处理完成后通知你"
                        })
                    else:
                        api_post("/api/send", {
                            "sender": args.name,
                            "content": f"❌ 任务创建失败: {result.get('error', 'unknown')}"
                        })
                else:
                    # No specialist matched — answer directly
                    online_list = ", ".join(online_agents) or "无"
                    specialists_list = ", ".join(s.get("name","") for s in specialists) or "无"
                    api_post("/api/send", {
                        "sender": args.name,
                        "content": f"📋 可用团队: {specialists_list}\n在线: {online_list}\n请描述你的需求，我来匹配最合适的人。"
                    })

            # ── Also handle own tasks (non-manager duties) ──
            result = api_post("/api/tasks/auto-claim", {
                "agent_id": agent_id, "capabilities": caps,
            })
            if result.get("claimed"):
                task = result.get("claimed", result)
                # Simple auto-reply for direct tasks to manager
                answer, thinking, aerr = call_ai(
                    task["title"], task.get("description", ""),
                    args.name, role, goal, backstory, caps,
                )
                result_text = answer if not aerr else f"Error: {aerr}"
                api_post(f"/api/tasks/{task['task_id']}/complete", {
                    "agent_id": agent_id, "result": result_text,
                })

        except urllib.error.URLError:
            safe_print(f"[MANAGER] Connection lost, retrying...")
        except KeyboardInterrupt:
            running = False
        except Exception as e:
            safe_print(f"[MANAGER] Error: {e}")

        if running:
            try:
                time.sleep(interval)
            except KeyboardInterrupt:
                running = False

    safe_print("[MANAGER] Shutting down. Bye.")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="A2A Agent Client v2")
    sp = p.add_subparsers(dest="cmd")

    # register
    sp_reg = sp.add_parser("register", help="Register agent with identity")
    sp_reg.add_argument("--name", required=True)
    sp_reg.add_argument("--role", default="")
    sp_reg.add_argument("--goal", default="")
    sp_reg.add_argument("--backstory", default="")
    sp_reg.add_argument("--capabilities", default="")
    sp_reg.add_argument("--model", default="")

    # manager
    sp_mgr = sp.add_parser("manager", help="Manager mode: listen to user, dispatch to specialists")
    sp_mgr.add_argument("--name", required=True)
    sp_mgr.add_argument("--role", default="Agent Orchestrator & User Proxy")
    sp_mgr.add_argument("--goal", default="Parse user intent, dispatch to specialists, summarize results")
    sp_mgr.add_argument("--backstory", default="")
    sp_mgr.add_argument("--capabilities", default="chat,task_orchestration,notification")
    sp_mgr.add_argument("--model", default="")
    sp_mgr.add_argument("--poll-interval", type=int, default=5)
    sp_mgr.add_argument("--verbose", action="store_true")

    # auto
    sp_auto = sp.add_parser("auto", help="Auto mode: register + poll + claim + execute")
    sp_auto.add_argument("--name", required=True)
    sp_auto.add_argument("--role", default="")
    sp_auto.add_argument("--goal", default="")
    sp_auto.add_argument("--backstory", default="")
    sp_auto.add_argument("--capabilities", default="")
    sp_auto.add_argument("--model", default="")
    sp_auto.add_argument("--poll-interval", type=int, default=5)
    sp_auto.add_argument("--verbose", action="store_true")
    sp_auto.add_argument("--once", action="store_true")
    sp_auto.add_argument("--auto-reply", action="store_true", help="Auto AI response (headless)")

    # create-task
    sp_ct = sp.add_parser("create-task", help="Create a task")
    sp_ct.add_argument("--title", required=True)
    sp_ct.add_argument("--desc", default="")
    sp_ct.add_argument("--capabilities", default="")
    sp_ct.add_argument("--priority", default="normal")
    sp_ct.add_argument("--creator", default="Anonymous")
    sp_ct.add_argument("--broadcast", action="store_true", help="Broadcast to all matching agents")
    sp_ct.add_argument("--context", default="", help="Comma-separated dependent task IDs")
    sp_ct.add_argument("--max-rounds", default="", help="GroupChat max rounds")
    sp_ct.add_argument("--approval-required", action="store_true", help="Require human approval")

    # tasks
    sp_ts = sp.add_parser("tasks", help="List tasks")
    sp_ts.add_argument("--status", default=None)

    # send / read / listen (legacy)
    sp_send = sp.add_parser("send", help="Send chat message")
    sp_send.add_argument("--name", required=True)
    sp_send.add_argument("--msg", required=True)

    sp_read = sp.add_parser("read", help="Read recent messages")
    sp_read.add_argument("--since", type=float, default=0)

    sp.add_parser("listen", help="Listen for messages continuously")

    args = p.parse_args()

    if args.cmd == "register":
        cmd_register(args)
    elif args.cmd == "manager":
        cmd_manager(args)
    elif args.cmd == "auto":
        cmd_auto(args)
    elif args.cmd == "create-task":
        cmd_create_task(args)
    elif args.cmd == "tasks":
        cmd_tasks(args)
    elif args.cmd == "send":
        cmd_send(args)
    elif args.cmd == "read":
        cmd_read(args)
    elif args.cmd == "listen":
        cmd_listen(args)
    else:
        p.print_help()
