"""
BPT_Data_Check — persistent keep-alive daemon.
Uses DETACHED_PROCESS, survives terminal close.
"""
import subprocess, sys, os, time, json, urllib.request

AGENT_ID = "BPT_Data_Check-fbc719"
HOST = "http://localhost:8765"

def heartbeat():
    data = json.dumps({"agent_id": AGENT_ID}).encode()
    req = urllib.request.Request(f"{HOST}/api/agents/heartbeat", data=data,
        headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=5)

if __name__ == "__main__":
    # If run without args: respawn self as detached process
    if len(sys.argv) == 1:
        DETACH = 0x00000008
        CREATE_NO_WINDOW = 0x08000000
        subprocess.Popen(
            [sys.executable, __file__, "--daemon"],
            creationflags=DETACH | CREATE_NO_WINDOW,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        print(f"BPT_Data_Check spawned as detached process ({AGENT_ID})")
        sys.exit(0)

    # Daemon mode — heartbeat loop forever
    print(f"BPT_Data_Check daemon started: {AGENT_ID}")
    while True:
        try:
            heartbeat()
        except Exception:
            pass
        time.sleep(30)
