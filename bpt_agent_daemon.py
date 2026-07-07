"""
BPT_Data_Check Agent Daemon — verified tooled agent keep-alive loop.
Keeps the agent online, polls for tasks, executes via the host Claude session.
"""
import urllib.request, json, time, os, sys

AGENT_ID = "BPT_Data_Check-0d6b0b"
HOST = "http://localhost:8765"
POLL = 30

def post(path, data):
    url = f"{HOST}{path}"
    body = json.dumps(data, ensure_ascii=False).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=10).read())

def get(path):
    return json.loads(urllib.request.urlopen(f"{HOST}{path}", timeout=10).read())

def main():
    print(f"BPT_Data_Check daemon started (agent_id={AGENT_ID})")
    print(f"Platform: {HOST}")
    print(f"Poll interval: {POLL}s")

    while True:
        try:
            # Heartbeat
            post("/api/agents/heartbeat", {"agent_id": AGENT_ID})

            # Check for chat messages
            try:
                msgs = get("/api/messages?since=0")
                for m in msgs:
                    if m.get("type") == "chat":
                        print(f"[CHAT] {m.get('sender')}: {m.get('content','')[:120]}")
            except:
                pass

            # Auto-claim tasks
            try:
                agent = get(f"/api/agents/{AGENT_ID}")
                caps = agent.get("capabilities", [])
                task = post("/api/tasks/auto-claim", {
                    "agent_id": AGENT_ID,
                    "capabilities": caps
                })
                if task and task.get("task_id"):
                    print(f"[TASK] Claimed: {task.get('title','')}")
                    # Mark as needing attention — the host Claude session handles actual execution
                    post("/api/agents/progress", {
                        "agent_id": AGENT_ID,
                        "task_id": task["task_id"],
                        "progress": "Task claimed by BPT_Data_Check. Waiting for execution by host Claude session at d:\\ClothesNetData."
                    })
            except Exception as e:
                pass

        except Exception as e:
            print(f"[ERR] {e}")

        time.sleep(POLL)

if __name__ == "__main__":
    main()
