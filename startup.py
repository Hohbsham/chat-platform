"""
A2A Platform v3 — OS-Level Wake-Up Startup
===========================================

Services: Server (:8765), Hub (:8767), Hermes (orchestrator)
Wake-up: Bash desktop watcher (signals → wake_vscode → Claude Hook)

Usage:
  python startup.py              # Start everything
  python startup.py --status     # Check what's running
"""
import subprocess, sys, os, time, json, ctypes

PYTHON = sys.executable
BASE = os.path.dirname(os.path.abspath(__file__))

DETACH = 0x00000008
CREATE_NO_WINDOW = 0x08000000
FLAGS = DETACH | CREATE_NO_WINDOW if sys.platform == "win32" else 0


def launch(name, args):
    """Spawn a detached background process."""
    proc = subprocess.Popen(
        [PYTHON] + args, cwd=BASE, creationflags=FLAGS,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print(f"  [{proc.pid}] {name}")
    return proc


def is_process_alive(pid):
    """Check if a Windows process is still running."""
    try:
        SYNCHRONIZE = 0x100000
        WAIT_TIMEOUT = 0x102
        handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if not handle:
            return False
        ret = ctypes.windll.kernel32.WaitForSingleObject(handle, 0)
        ctypes.windll.kernel32.CloseHandle(handle)
        return ret == WAIT_TIMEOUT
    except Exception:
        return False


def start_hub():
    print("[1/4] Webhook Hub...")
    return launch("WebhookHub", ["webhook_hub.py"])


def start_server():
    print("[2/4] A2A Server...")
    return launch("Server", ["server.py", "--port", "8765"])


def start_hermes():
    print("[3/4] Hermes Orchestrator...")
    return launch("Hermes", ["hermes_agent.py", "--poll-interval", "10"])


def start_desktop_watcher():
    """Bash loop watching signals/ — runs wake_vscode.py from desktop session.
    NOT a Python subprocess (pyautogui needs real terminal session).
    Started manually or via the bash command below."""
    print("[4/4] Desktop Watcher: run manually in terminal —")
    print(f"      cd {BASE} && while true; do")
    print(f"        for f in signals/*.json; do")
    print(f'          [ -f \"$f\" ] || continue')
    print(f'          agent=$(basename \"$f\" .json)')
    print(f'          python scripts/wake_vscode.py \"$agent\"')
    print(f"        done")
    print(f"        sleep 2")
    print(f"      done")
    return None


def start_all():
    print("=" * 50)
    print("  A2A Platform v3 — OS-Level Wake-Up")
    print("  Task → Signal → Watcher → wake_vscode → Hook → Claude")
    print("=" * 50)

    procs = {}
    procs["hub"] = start_hub()
    time.sleep(1)
    procs["server"] = start_server()
    time.sleep(1)
    procs["hermes"] = start_hermes()
    start_desktop_watcher()

    print(f"\n  A2A:  http://localhost:8765")
    print(f"  Hub:  http://localhost:8767/health")
    print(f"  Tunnel: cat .public_url")
    print("=" * 50)
    return procs


def watchdog_loop(procs):
    """Monitor services. Restart dead ones."""
    restart = {
        "hub": start_hub,
        "server": start_server,
        "hermes": start_hermes,
    }
    pid_map = {p.pid: name for name, p in procs.items() if p}

    print(f"\n[Watchdog] Monitoring {len(pid_map)} services...\n")
    while True:
        time.sleep(15)
        for pid, name in list(pid_map.items()):
            if not is_process_alive(pid):
                print(f"  [DEAD] {name} — restarting...")
                try:
                    new_proc = restart[name]()
                    pid_map[new_proc.pid] = name
                    print(f"  [OK] {name} restarted (PID {new_proc.pid})")
                except Exception as e:
                    print(f"  [FAIL] {name}: {e}")
        pid_map = {pid: name for pid, name in pid_map.items() if is_process_alive(pid)}


def check_status():
    import urllib.request
    try:
        r = json.loads(urllib.request.urlopen(
            "http://localhost:8765/api/health", timeout=5).read())
        print(f"  Server: RUNNING ({r['uptime']:.0f}s)")
        print(f"  Agents: {r['agents_online']}/{r['agents_total']} online")
        print(f"  Tasks: {r['tasks_pending']} pending / {r['tasks_total']} total")
        print(f"  DB: {r['db_size_kb']}kb")
    except Exception:
        print("  Server: DOWN")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        procs = start_all()
        try:
            watchdog_loop(procs)
        except KeyboardInterrupt:
            print("\n[Watchdog] Shutting down...")
            for p in procs.values():
                if p:
                    try: p.terminate()
                    except Exception: pass
    elif sys.argv[1] == "--status":
        check_status()
    else:
        print("Usage: python startup.py [--status]")
