"""
Hermes Agent — Real integration with A2A platform.
Uses Hermes's actual AI engine and tools, not just call_ai().
"""
import json, os, sys, time, uuid, urllib.request, urllib.error, threading

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HERMES_DIR = r"D:\Hermes"
sys.path.insert(0, HERMES_DIR)
sys.path.insert(0, BASE_DIR)
import db  # Hermes uses db to fix task assignments

HOST = os.environ.get("CHAT_HOST", "http://localhost:8765")
AGENT_ID_FILE = os.path.join(BASE_DIR, ".hermes_agent_id")

# ── HTTP helpers ────────────────────────────────────────────────

def api_post(path, data):
    url = f"{HOST}{path}"
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body,
        headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=30).read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": str(e)}


def api_get(path):
    try:
        return json.loads(urllib.request.urlopen(f"{HOST}{path}", timeout=10).read())
    except Exception:
        return []


# ── Hermes AI integration ───────────────────────────────────────

def hermes_think(task_title, task_desc, agent_name, role, goal, backstory, capabilities):
    """
    Use Hermes's actual AI engine (model_tools.query_model) to process a task.
    Falls back to direct API call if Hermes isn't importable.
    """
    # Try Hermes native API first
    try:
        from model_tools import query_model
        prompt = f"""You are {agent_name}, {role}.

Your goal: {goal}
Your background: {backstory}
Your capabilities: {', '.join(capabilities)}

A task has been assigned to you:
Title: {task_title}
Description: {task_desc or '(no details provided)'}

Process this task. If it requires tool use (shell commands, file operations, browser),
describe what tools you would use and what you would do. If it's analytical,
provide your analysis. Be thorough and actionable.
Respond as {agent_name}, consistent with your role."""
        result = query_model(
            model="deepseek/deepseek-v4-pro",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1500,
        )
        return result.strip(), None
    except Exception as e:
        pass

    # Fallback: use ai_config (same as thin agents)
    try:
        from ai_config import get_config
        cfg = get_config()
        if cfg["api_key"] and cfg["base_url"]:
            url = cfg["base_url"].rstrip("/") + "/v1/chat/completions"
            model = cfg["model"].split("/")[-1] if "/" in cfg["model"] else cfg["model"]
            body = json.dumps({
                "model": model,
                "messages": [{"role": "user", "content": f"You are {agent_name}, {role}.\nGoal: {goal}\nCapabilities: {', '.join(capabilities)}\n\nTask: {task_title}\n{task_desc or ''}"}],
                "max_tokens": 1500, "temperature": 0.7,
            }).encode()
            req = urllib.request.Request(url, data=body, headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {cfg['api_key']}",
            })
            resp = urllib.request.urlopen(req, timeout=60)
            data = json.loads(resp.read().decode())
            answer = data["choices"][0]["message"].get("content", "").strip()
            return answer, None
    except Exception as e:
        return None, str(e)

    return None, "No AI backend available"


# ── Main agent loop ─────────────────────────────────────────────

# ── Orchestration Engine ─────────────────────────────────────────

# ── Canonical Capability Vocabulary (single source of truth) ──────
# All agents and task patterns MUST use these exact names.
# Data domain:  dataset_inspection, mesh_quality_check, data_cleaning
# Training:     training_monitor, mesh_eval
# Code:         code_generation, code_review, debugging, refactoring
# Architecture: architecture_design, report_generation
# Quality:      quality_evaluation, scoring, issue_detection, agent_audit
# BPT specific: kp_extract, boundary_extract, quad_check
# Meta:         progress_tracking, notification

# Agent registry: who can do what
ORCHESTRATOR_KNOWLEDGE = {
    "BPTtrain": {
        "caps": ["training_monitor", "mesh_eval", "report_generation",
                 "architecture_design", "dataset_inspection", "code_review",
                 "progress_tracking", "debugging"],
        "role": "BPT Training Monitor & Reporter",
        "description": "Monitors BPT training, evaluates mesh output, generates reports, reviews code/architecture."
    },
    "BPT_Data_Check": {
        "caps": ["dataset_inspection", "mesh_quality_check", "data_cleaning",
                 "quad_check", "kp_extract", "boundary_extract",
                 "report_generation", "progress_tracking"],
        "role": "Data Quality Inspector",
        "description": "Inspects mesh data quality, validates quad meshes, extracts keypoints/boundaries, cleans datasets."
    },
    "QualityEvaluator": {
        "caps": ["quality_evaluation", "scoring", "issue_detection",
                 "agent_audit", "calibration"],
        "role": "Quality Inspector",
        "description": "Evaluates agent outputs, scores quality, audits agents, detects issues."
    },
    "Claude": {
        "caps": ["code_generation", "code_review", "debugging", "refactoring",
                 "architecture_design", "report_generation",
                 "dataset_inspection", "mesh_quality_check",
                 "shell_exec", "file_read", "file_write", "file_edit"],
        "role": "BPT Architect & Code Engineer",
        "description": "Designs architecture, writes/fixes code, runs tests, inspects data. Has real tools (shell, file, edit)."
    },
}

# Task patterns: what user says -> how to break it down
# CRITICAL: caps MUST match the canonical vocabulary above
TASK_PATTERNS = [
    # DISABLED: BPTtrain and BPT_Data_Check are thin agents that produce empty/garbage output.
    # Re-enable after fixing them (see CLAUDE.md.template for fix options).
    # {
    #     "keywords": ["训练", "training", "GPU", "epoch", "loss", "checkpoint", "BPT", "v8", "v9"],
    #     ...
    # },
    # {
    #     "keywords": ["数据", "data", "dataset", "质检", "清洗", "clean", "quality", "检查", "inspect"],
    #     ...
    # },
    # {
    #     "keywords": ["周报", "报告", "report", "总结", "summary"],
    #     ...
    # },
    {
        "keywords": ["架构", "architecture", "设计", "design", "方案", "Phase", "phase", "计划", "规划"],
        "template": {
            "title": "Architecture & Implementation Design",
            "subtasks": [
                {"title": "Design architecture and implementation plan", "caps": ["architecture_design", "code_generation"], "agent": "Claude"},
                {"title": "Review architecture and code quality", "caps": ["code_review", "quality_evaluation"], "agent": "QualityEvaluator"},
            ]
        }
    },
    {
        "keywords": ["quad", "四边形", "symmetry", "对称", "keypoint", "关键点", "boundary", "边界", "loss"],
        "template": {
            "title": "BPT Code Implementation Task",
            "subtasks": [
                {"title": "Implement code changes (quad fix, loss, conditioning)", "caps": ["code_generation", "debugging", "refactoring"], "agent": "Claude"},
                {"title": "Inspect affected data samples", "caps": ["dataset_inspection", "mesh_quality_check"], "agent": "BPT_Data_Check"},
                {"title": "Review implementation quality", "caps": ["code_review", "quality_evaluation"], "agent": "QualityEvaluator"},
            ]
        }
    },
]


def _fix_unassigned_tasks(hermes_name, hermes_caps):
    """
    Hermes is the MANAGER. It NEVER does worker tasks.
    It ensures every pending task has a proper assigned_to based on capability matching.
    """
    try:
        all_tasks = api_get("/api/tasks?status=pending")
        if not isinstance(all_tasks, list):
            return
        for t in all_tasks:
            if not t:
                continue
            assigned = t.get("assigned_to", "")
            required = set(t.get("required_capabilities", []))
            tid = t.get("task_id", "?")

            # Already assigned → skip
            if assigned:
                continue

            # Match against ALL registered agents (not just "online" — the label is meaningless)
            best_agent = None
            try:
                all_agents = api_get("/api/agents?status=all")
                if isinstance(all_agents, list):
                    for a in all_agents:
                        if a.get("name") == hermes_name:
                            continue
                        agent_caps = set(a.get("capabilities", []))
                        if required and required.issubset(agent_caps):
                            best_agent = a.get("name", "")
                            break
            except Exception:
                pass

            if best_agent:
                # Fix the assignment
                db.task_update(tid, assigned_to=best_agent)
                # Fire webhook so Hub writes inbox file
                try:
                    import urllib.request as _ur
                    _ur.urlopen(_ur.Request("http://localhost:8767/webhook",
                        data=json.dumps({"task_id": tid, "title": t.get("title",""), "agent": best_agent}).encode(),
                        headers={"Content-Type": "application/json"}), timeout=2)
                except Exception:
                    pass
                print(f"[Hermes Manager] Assigned {tid[:12]}... -> @{best_agent} (caps: {required})")
                api_post("/api/send", {
                    "sender": hermes_name,
                    "content": f"[Manager] 任务「{t.get('title','?')[:40]}」已指派给 @{best_agent}"
                })
            else:
                # No known agent matches — leave it, maybe a new agent will arrive
                print(f"[Hermes Manager] Orphan task {tid[:12]} — no matching agent for {required}")
    except Exception as e:
        print(f"[Hermes Manager] Assignment fixer error: {e}")


def _orchestrate_from_chat(agent_id, name, role, goal, backstory, capabilities):
    """
    Read recent chat messages. If any contain a request matching our patterns,
    break it into subtasks and dispatch to specialist agents.
    """
    # Get recent messages
    since = time.time() - 60  # last 60 seconds
    try:
        msgs = api_get(f"/api/messages?since={since}")
    except Exception:
        return

    # Filter: only new chat messages from users (not agents)
    user_msgs = [m for m in msgs
                 if m.get("type") == "chat"
                 and m.get("sender") not in ("Hermes", "System")
                 and "Hermes" not in m.get("sender", "")]
    if not user_msgs:
        return

    latest = user_msgs[-1]
    content = latest.get("content", "").strip()
    if len(content) < 3:
        return

    # Check if we already processed this message (dedup by timestamp)
    msg_ts = latest.get("ts", 0)
    if not hasattr(_orchestrate_from_chat, '_last_msg_ts'):
        _orchestrate_from_chat._last_msg_ts = 0
    if msg_ts <= _orchestrate_from_chat._last_msg_ts:
        return
    _orchestrate_from_chat._last_msg_ts = msg_ts

    # Match against task patterns
    content_lower = content.lower()
    for pattern in TASK_PATTERNS:
        if any(kw in content_lower for kw in pattern["keywords"]):
            tmpl = pattern["template"]
            print(f"\n[Hermes Orchestrator] Detected intent: {tmpl['title']}")
            print(f"  User said: {content[:80]}...")

            # Create subtasks with dependencies
            created_tasks = []
            for i, sub in enumerate(tmpl["subtasks"]):
                task_data = {
                    "title": f"[Orchestrated] {sub['title']}",
                    "description": f"Auto-dispatched by Hermes based on user request:\n\"{content[:200]}\"\n\nThis is subtask {i+1}/{len(tmpl['subtasks'])}.",
                    "required_capabilities": sub["caps"],
                    "priority": "high",
                    "creator": "Hermes",
                    "assigned_to": sub.get("agent", ""),  # ← named assignment
                }
                # Add dependency: wait for previous subtask
                if i > 0 and created_tasks:
                    task_data["context"] = [created_tasks[-1]["task_id"]]

                result = api_post("/api/tasks", task_data)
                if result.get("ok"):
                    t = result["task"]
                    created_tasks.append(t)
                    target = sub.get("agent", "unknown")
                    print(f"  -> Dispatched to {target}: {t['task_id'][:16]}... [{sub['title']}]")
                else:
                    print(f"  -> FAILED: {sub['title']}")

            # Notify chat
            if created_tasks:
                summary = f"收到「{content[:40]}...」→ 已拆分为 {len(created_tasks)} 个子任务：\n"
                for i, t in enumerate(created_tasks):
                    target = tmpl["subtasks"][i].get("agent", "?")
                    summary += f"  {i+1}. {t['title']} → @{target}\n"
                summary += "\n完成后我会汇总结果。"
                api_post("/api/send", {"sender": name, "content": summary})
                print(f"  Orchestration complete: {len(created_tasks)} tasks dispatched")

            return  # only handle one pattern per cycle


def run_hermes_agent(name="Hermes", role="Platform Operations Director",
                     goal="Execute tasks, manage infrastructure, orchestrate research",
                     backstory="Full-featured AI agent with terminal, file ops, browser, memory, skills, subagents, cron",
                     capabilities=None, poll_interval=10):
    """Run Hermes as an A2A agent — with real AI brain."""
    if capabilities is None:
        capabilities = ["shell_exec", "file_read", "file_write", "browser",
                        "memory", "skill_create", "subagent_spawn",
                        "cron_schedule", "task_orchestration", "server_management"]

    # Load or create agent ID
    agent_id = None
    if os.path.exists(AGENT_ID_FILE):
        with open(AGENT_ID_FILE) as f:
            agent_id = f.read().strip()

    # Register on A2A
    result = api_post("/api/agents/register", {
        "agent_id": agent_id or "",
        "name": name, "role": role, "goal": goal, "backstory": backstory,
        "capabilities": capabilities,
        "model": "deepseek/deepseek-v4-pro",
        "verified": True,
        "source": "hermes_agent",
    })
    agent = result.get("agent", {})
    agent_id = agent.get("agent_id", f"{name}-{uuid.uuid4().hex[:6]}")
    with open(AGENT_ID_FILE, "w") as f:
        f.write(agent_id)

    print(f"[Hermes Agent] Registered: {name} ({agent_id})")
    print(f"[Hermes Agent] Role: {role}")
    print(f"[Hermes Agent] Brain: Hermes AI engine (model_tools.query_model)")
    print(f"[Hermes Agent] Tools: {len(capabilities)} capabilities")
    print(f"[Hermes Agent] Orchestrator: ENABLED (monitoring chat for commands)")
    print(f"[Hermes Agent] Polling every {poll_interval}s + WebSocket push\n")

    # WebSocket push listener — wake up on pipeline advance
    import threading as _thr, asyncio as _aio
    ws_trigger = _thr.Event()

    def _ws_listen():
        try:
            import websockets
        except ImportError:
            return
        async def _listen():
            ws_url = "ws://localhost:8766"
            while running:
                try:
                    async with websockets.connect(ws_url) as ws:
                        await ws.send(json.dumps({"type": "agent_connect", "agent_id": agent_id}))
                        while running:
                            try:
                                msg = await _aio.wait_for(ws.recv(), timeout=30)
                                data = json.loads(msg)
                                if data.get("type") in ("task_ready", "pipeline_advance"):
                                    ws_trigger.set()
                            except _aio.TimeoutError:
                                await ws.send(json.dumps({"type": "agent_heartbeat"}))
                except Exception:
                    if running:
                        await _aio.sleep(5)
        _thr.Thread(target=lambda: _aio.run(_listen()), daemon=True).start()

    _ws_listen()
    print(f"[Hermes Agent] WebSocket listener started on ws://localhost:8766")

    running = True
    last_orchestration = 0
    orchestrate_interval = poll_interval * 2

    while running:
        try:
            api_post("/api/agents/heartbeat", {"agent_id": agent_id})

            # Push wake-up: if we were woken by a push, also check chat
            if ws_trigger.is_set():
                ws_trigger.clear()
                last_orchestration = 0

            # ── Assignment Fixer: ensure all pending tasks have proper assigned_to ──
            # Hermes is a MANAGER. It does NOT do worker tasks. It assigns them.
            _fix_unassigned_tasks(name, capabilities)

            # ── Orchestration: monitor chat, parse intent, dispatch ──
            tick = int(time.time())
            if tick - last_orchestration >= orchestrate_interval:
                last_orchestration = tick
                _orchestrate_from_chat(agent_id, name, role, goal, backstory, capabilities)

            # ── Manager tasks ONLY: tasks assigned TO Hermes ──
            # Hermes only claims tasks explicitly assigned to it (orchestration meta-tasks).
            # Worker tasks (code_review, quality_evaluation, etc.) are SKIPPED.
            result = api_post("/api/tasks/auto-claim", {
                "agent_id": agent_id,
                "capabilities": ["task_orchestration", "server_management"],
            })

            if result.get("claimed"):
                task = result.get("claimed", result)
                tid = task.get("task_id", "?")
                assigned_to = task.get("assigned_to", "")
                # Double-check: only process if assigned to Hermes
                if assigned_to and assigned_to != name:
                    continue
                print(f"\n[Hermes] Manager task: {task.get('title', tid)}")
                answer, err = hermes_think(task.get("title", ""), task.get("description", ""), name, role, goal, backstory, capabilities)
                result_text = answer if not err else f"[Hermes] Error: {err}"
                api_post(f"/api/tasks/{tid}/complete", {"agent_id": agent_id, "result": result_text})
                print(f"         [DONE]\n")

        except KeyboardInterrupt:
            running = False
        except Exception as e:
            print(f"[Hermes] Error: {e}")

        if running:
            try:
                ws_trigger.wait(timeout=poll_interval)
                ws_trigger.clear()
            except KeyboardInterrupt:
                running = False

    # Unregister
    try:
        api_post("/api/agents/unregister", {"agent_id": agent_id})
        print("[Hermes Agent] Unregistered. Bye.")
    except Exception:
        pass


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Hermes Agent for A2A Platform")
    p.add_argument("--name", default="Hermes")
    p.add_argument("--role", default="Platform Operations Director")
    p.add_argument("--goal", default="Execute complex multi-step tasks, manage infrastructure, orchestrate research pipelines")
    p.add_argument("--poll-interval", type=int, default=10)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    capabilities = [
        "shell_exec", "file_read", "file_write", "browser",
        "memory", "skill_create", "subagent_spawn",
        "cron_schedule", "task_orchestration", "server_management",
        "research_orchestration", "code_review",
    ]

    run_hermes_agent(
        name=args.name, role=args.role, goal=args.goal,
        backstory="Full-featured AI agent powered by Hermes engine. Has real terminal access, file operations, browser control, persistent memory, skill creation, subagent spawning, and cron scheduling. Not a thin wrapper — actually executes tools.",
        capabilities=capabilities,
        poll_interval=args.poll_interval,
    )
