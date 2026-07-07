"""Quick E2E test for Webhook Hub."""
import urllib.request, json, time, sys

HUB = "http://localhost:8767"
A2A = "http://localhost:8765"

def post(host, path, data):
    req = urllib.request.Request(f"{host}{path}",
        data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=5).read())

def get(host, path):
    return json.loads(urllib.request.urlopen(f"{host}{path}", timeout=5).read())

# 1. Hub health
try:
    h = get(HUB, "/health")
    print(f"[OK] Hub: {h['stats']}")
except Exception as e:
    print(f"[FAIL] Hub: {e}")
    sys.exit(1)

# 2. A2A health
try:
    a = get(A2A, "/api/health")
    print(f"[OK] A2A: {a['agents_online']} agents")
except Exception as e:
    print(f"[FAIL] A2A: {e}")
    sys.exit(1)

# 3. Create task (A2A fires webhook to Hub)
r = post(A2A, "/api/tasks", {
    "title": "Webhook E2E Test",
    "required_capabilities": ["quality_evaluation"],
    "assigned_to": "QualityEvaluator",
    "priority": "high",
    "creator": "Test"
})
tid = r["task"]["task_id"]
print(f"[OK] Task: {tid[:16]}...")

time.sleep(1)

# 4. Hub received it
pending = get(HUB, "/pending")
print(f"[OK] Hub pending: {len(pending)}")
for t in pending:
    print(f"  [{t['status']}] {t['title']} -> {t['agent']}")

if len(pending) == 0:
    print("[WARN] Hub didn't receive webhook! Check server.py _fire_webhook()")
    sys.exit(1)

# 5. Claim
r = post(HUB, "/claim", {"task_id": tid, "agent_id": "Claude-IDE"})
print(f"[OK] Claim: {r['msg']}")

# 6. Check claimed
pending2 = get(HUB, "/pending")
claimed = [t for t in pending2 if t["status"] == "claimed"]
print(f"[OK] Claimed: {len(claimed)}")

# 7. Done
r = post(HUB, "/done", {"task_id": tid, "result": "E2E PASSED"})
print(f"[OK] Done: {r['ok']}")

# 8. Verify empty
pending3 = get(HUB, "/pending")
assert len(pending3) == 0, f"Hub not empty: {len(pending3)} tasks"
print(f"\n=== WEBHOOK HUB E2E: PASSED ===")
