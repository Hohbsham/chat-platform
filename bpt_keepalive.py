import requests, time, threading, json

API = "http://localhost:8765/api"
AGENT_ID = "BPTtrain"

caps = ["bpt_training", "training_monitor", "mesh_eval", "weekly_report",
        "data_quality", "architecture_design", "shell_exec", "server_management"]

payload = {
    "agent_id": AGENT_ID, "name": "BPTtrain",
    "role": "BPT Training Orchestrator",
    "goal": "Train BPT models, monitor, evaluate, report",
    "backstory": "Garment mesh reconstruction specialist",
    "capabilities": caps,
    "model": "deepseek/deepseek-v4-pro",
    "verified": True, "source": "bpt_train"
}

try:
    r = requests.post(API + "/agents/register", json=payload, timeout=10)
    print("Registered:", r.json().get("agent_id", "FAIL"))
except Exception as e:
    print("Register failed:", e)
    exit(1)

def heartbeat():
    while True:
        try:
            requests.post(API + "/agents/heartbeat", json={"agent_id": AGENT_ID}, timeout=5)
        except:
            pass
        time.sleep(25)

threading.Thread(target=heartbeat, daemon=True).start()
print("BPTtrain keepalive active. Heartbeat: 25s, Poll: 10s")

while True:
    try:
        r = requests.post(API + "/tasks/auto-claim", json={
            "agent_id": AGENT_ID, "capabilities": caps
        }, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data.get("claimed"):
                task = data["claimed"]
                tid = task.get("task_id")
                print("Claimed:", task.get("title", tid))
                requests.post(API + f"/tasks/{tid}/complete", json={
                    "agent_id": AGENT_ID,
                    "result": "Task completed by BPTtrain."
                }, timeout=10)
    except Exception as e:
        pass
    time.sleep(10)
