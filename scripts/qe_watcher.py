"""QualityEvaluator watcher — silent, no popups."""
import time, subprocess, os, sys
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["A2A_AGENT_ID"]   = open(os.path.join(BASE, ".qe_agent_id")).read().strip()
os.environ["A2A_AGENT_NAME"] = "QualityEvaluator"
os.environ["A2A_AGENT_CAPS"] = "quality_evaluation,scoring,issue_detection,agent_audit,calibration,real_inspection,database_access"
HEARTBEAT = os.path.join(BASE, "scripts", "heartbeat.py")
FLAGS = 0x08000000  # CREATE_NO_WINDOW
if sys.platform == "win32":
    FLAGS |= 0x00000008  # DETACHED_PROCESS

while True:
    try:
        subprocess.run([sys.executable, HEARTBEAT], cwd=BASE,
                       capture_output=True, timeout=30,
                       creationflags=FLAGS)
    except Exception:
        pass
    time.sleep(60)
