"""
Hermes ↔ A2A Bridge — Hermes as the Manager Agent
Hermes monitors chat, parses user intent, dispatches to A2A specialists.

Usage:
  python hermes_bridge.py --a2a-host http://localhost:8765
"""
import json, os, sys, time, urllib.request, uuid

A2A_HOST = os.environ.get("CHAT_HOST", "http://localhost:8765")
HERMES_DIR = r"D:\Hermes"
sys.path.insert(0, HERMES_DIR)

def api_post(path, data):
    url = f"{A2A_HOST}{path}"
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body,
        headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=10).read())
    except Exception as e:
        return {"ok": False, "error": str(e)}

def api_get(path):
    try:
        return json.loads(urllib.request.urlopen(f"{A2A_HOST}{path}", timeout=10).read())
    except Exception:
        return []

def register_hermes():
    agent_id = f"Hermes-{uuid.uuid4().hex[:6]}"
    with open(os.path.join(os.path.dirname(__file__), ".hermes_id"), "w") as f:
        f.write(agent_id)
    return api_post("/api/agents/register", {
        "agent_id": agent_id, "name": "Hermes",
        "role": "Agent Orchestrator & Gateway Manager",
        "goal": "Parse user intent, dispatch tasks to specialists, wake offline agents",
        "backstory": "Successor to OpenClaw. 23k+ stars. Manages 27+ messaging channels.",
        "capabilities": ["chat", "task_orchestration", "agent_management", "notification"],
        "model": "deepseek/deepseek-v4-pro",
    })

def load_registry():
    for p in [os.path.join(os.path.dirname(__file__), "agent_registry.json")]:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
    return {"specialists": []}

def hermes_ai_parse(user_msg):
    """Use Hermes AI to parse user intent into structured task."""
    try:
        from run_agent import main as hermes_run
        # Use model_tools for quick single-pass inference
        from model_tools import query_model

        prompt = f"""You are Hermes, the orchestrator of an agent team.
A user just sent this message: "{user_msg}"

Your job: parse the user's intent and determine:
1. What is the user asking for? (1 sentence summary)
2. What specialist agent capabilities are needed? (pick from: paper_review, ai_detection, code_review, file_edit, debugging, chat, task_orchestration)
3. What is the task title? (short, <60 chars)

Respond in JSON:
{{"summary": "...", "capabilities_needed": ["..."], "task_title": "..."}}"""

        result = query_model(
            model="deepseek/deepseek-v4-pro",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
        )
        # Extract JSON from response
        import re
        match = re.search(r'\{.*\}', result, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        pass

    # Fallback: simple keyword matching
    content_lower = user_msg.lower()
    if any(w in content_lower for w in ["论文", "paper", "审阅", "review"]):
        return {"summary": "Paper review request", "capabilities_needed": ["paper_review"], "task_title": user_msg[:60]}
    if any(w in content_lower for w in ["代码", "code", "bug", "review"]):
        return {"summary": "Code-related request", "capabilities_needed": ["code_review"], "task_title": user_msg[:60]}
    return {"summary": "General request", "capabilities_needed": ["chat"], "task_title": user_msg[:60]}

def main():
    import argparse
    p = argparse.ArgumentParser(description="Hermes ↔ A2A Bridge")
    p.add_argument("--a2a-host", default=A2A_HOST, help="A2A platform URL")
    p.add_argument("--interval", type=int, default=5, help="Poll interval (seconds)")
    args = p.parse_args()

    global A2A_HOST
    A2A_HOST = args.a2a_host

    # Register Hermes
    result = register_hermes()
    agent_id = result.get("agent", {}).get("agent_id", "?")
    print(f"[Hermes] Registered as {agent_id}")
    print(f"[Hermes] A2A Platform: {A2A_HOST}")
    print(f"[Hermes] Listening for user requests...\n")

    registry = load_registry()
    last_ts = time.time()
    dispatched = set()

    while True:
        try:
            # Heartbeat
            api_post("/api/agents/heartbeat", {"agent_id": agent_id})

            # Observe user messages
            observed = api_post("/api/agents/observe", {
                "agent_id": agent_id, "since": last_ts,
            })
            msgs = observed.get("observed", [])
            user_msgs = [m for m in msgs
                        if m.get("type") == "chat"
                        and m.get("sender") not in ("Hermes", "System")]

            if user_msgs:
                latest = user_msgs[-1]
                content = latest.get("content", "")
                last_ts = max(m.get("ts", 0) for m in msgs) + 0.1

                print(f"[Hermes] User: {content[:80]}...")

                # Parse intent
                intent = hermes_ai_parse(content)
                caps_needed = intent.get("capabilities_needed", ["chat"])
                task_title = intent.get("task_title", content[:60])

                # Find matching specialist
                specialists = registry.get("specialists", [])
                online = [a["name"] for a in api_get("/api/agents") if a.get("status") == "online"]
                matched = next((s for s in specialists
                               if any(c in s.get("capabilities",[]) for c in caps_needed)
                               and s["name"] != "Hermes"), None)

                if matched:
                    if matched["name"] not in online:
                        print(f"[Hermes] {matched['name']} offline, waking...")
                        api_post("/api/send", {
                            "sender": "Hermes",
                            "content": f"🔔 {matched['name']} 当前离线，正在唤醒..."
                        })
                        time.sleep(3)

                    result = api_post("/api/tasks", {
                        "title": task_title,
                        "description": content,
                        "required_capabilities": matched.get("capabilities", caps_needed),
                        "priority": "high",
                        "creator": "Hermes",
                        "broadcast": False,
                    })
                    if result.get("ok"):
                        tid = result["task"]["task_id"]
                        dispatched.add(tid)
                        api_post("/api/send", {
                            "sender": "Hermes",
                            "content": f"📋 已分派「{task_title}」给 {matched['name']}"
                        })
                        print(f"[Hermes] → {matched['name']}: {task_title}")
                else:
                    api_post("/api/send", {
                        "sender": "Hermes",
                        "content": f"没有匹配的 specialist。可用: {', '.join(s['name'] for s in specialists)}"
                    })

            # Check completed tasks
            for tid in list(dispatched):
                t = api_get(f"/api/tasks/{tid}")
                if isinstance(t, dict) and t.get("status") == "completed":
                    result = (t.get("result") or "")[:300]
                    api_post("/api/send", {
                        "sender": "Hermes",
                        "content": f"✅ {t.get('completed_by','specialist')} 完成了「{t.get('title','')}」:\n{result}"
                    })
                    dispatched.discard(tid)

        except Exception as e:
            print(f"[Hermes] Error: {e}")

        time.sleep(args.interval)

if __name__ == "__main__":
    main()
