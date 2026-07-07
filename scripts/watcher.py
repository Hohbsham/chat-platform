"""Silent heartbeat watcher — 1 process, 30s cycle, NO popup windows."""
import time, subprocess, os, sys
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEARTBEAT = os.path.join(BASE, "scripts", "heartbeat.py")
FLAGS = 0x08000000  # CREATE_NO_WINDOW — suppress CMD popup
if sys.platform == "win32":
    FLAGS |= 0x00000008  # DETACHED_PROCESS

while True:
    try:
        subprocess.run([sys.executable, HEARTBEAT], cwd=BASE,
                       capture_output=True, timeout=30,
                       creationflags=FLAGS)
    except Exception:
        pass
    time.sleep(30)
