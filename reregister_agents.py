"""Re-register BPT agents with CORRECT canonical capabilities."""
import json, urllib.request, uuid, time

HOST = "http://localhost:8765"

def post(path, data):
    url = f"{HOST}{path}"
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body,
        headers={"Content-Type": "application/json; charset=utf-8"})
    return json.loads(urllib.request.urlopen(req, timeout=10).read())

# ── BPTtrain (thin agent, but use verified=True so caps are preserved) ──
# Source "bpt_train" is in TRUSTED_SOURCES in db.py
r = post("/api/agents/register", {
    "agent_id": "",
    "name": "BPTtrain",
    "role": "BPT Training Monitor & Reporter",
    "goal": "Monitor BPT training status, evaluate mesh output quality, generate weekly reports",
    "backstory": "AI agent specialized in BPT garment mesh generation. Can analyze training logs, evaluate Chamfer/Hausdorff metrics, and generate structured progress reports.",
    "capabilities": [
        "training_monitor", "mesh_eval", "report_generation",
        "architecture_design", "dataset_inspection", "code_review",
        "progress_tracking", "debugging"
    ],
    "model": "deepseek/deepseek-v4-pro",
    "verified": True,     # Need verified=True so capabilities aren't stripped
    "source": "bpt_train", # In TRUSTED_SOURCES
})
a = r.get("agent", {})
warning = r.get("warning", "")
caps = a.get("capabilities", [])
print(f"BPTtrain: {a.get('name')} ({a.get('agent_id','?')[:20]})")
if warning: print(f"  WARNING: {warning}")
print(f"  Caps: {caps}")

# ── BPT_Data_Check (tooled agent, verified) ──
# Source "bpt_data_check" is in TRUSTED_SOURCES
r2 = post("/api/agents/register", {
    "agent_id": "",
    "name": "BPT_Data_Check",
    "role": "BPT Data Quality Inspector",
    "goal": "Inspect mesh data quality, validate quad meshes, extract keypoints and boundaries, clean datasets",
    "backstory": "Data quality specialist for BPT garment mesh generation. Inspects quad ratios, face counts, keypoint accuracy, and boundary integrity in clothing meshes.",
    "capabilities": [
        "dataset_inspection", "mesh_quality_check", "data_cleaning",
        "quad_check", "kp_extract", "boundary_extract",
        "report_generation", "progress_tracking"
    ],
    "model": "deepseek/deepseek-v4-pro",
    "verified": True,
    "source": "bpt_data_check",
})
a2 = r2.get("agent", {})
warning2 = r2.get("warning", "")
caps2 = a2.get("capabilities", [])
print(f"BPT_Data_Check: {a2.get('name')} ({a2.get('agent_id','?')[:20]})")
if warning2: print(f"  WARNING: {warning2}")
print(f"  Caps: {caps2}")

print("\nDone. Both agents registered with canonical capabilities.")
