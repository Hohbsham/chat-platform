"""
Public tunnel — exposes A2A platform to the internet via Serveo.
Uses SSH reverse tunnel. No auth. No install. Free.

Starts as detached process. Saves public URL to .public_url file.
"""
import subprocess, sys, os, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL_FILE = os.path.join(BASE, ".public_url")

SSH_CMD = [
    "ssh", "-T",
    "-o", "StrictHostKeyChecking=no",
    "-o", "ServerAliveInterval=30",
    "-o", "ExitOnForwardFailure=yes",
    "-R", "80:localhost:8765",
    "serveo.net",
]

while True:
    try:
        proc = subprocess.Popen(
            SSH_CMD,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
            creationflags=0x00000008 | 0x08000000,  # DETACHED + NO_WINDOW
        )

        # Extract the public URL from serveo output
        for line in proc.stderr:
            if "Forwarding HTTP traffic from" in line:
                import re
                match = re.search(r'https://[\w.-]+\.serveo[a-z]+\.com', line)
                if match:
                    url = match.group(0)
                    with open(URL_FILE, "w") as f:
                        f.write(url + "\n")
                    print(f"[Tunnel] Public URL: {url}")
                    break

        proc.wait()
        print("[Tunnel] SSH disconnected, reconnecting in 10s...")
        time.sleep(10)
    except Exception as e:
        print(f"[Tunnel] Error: {e}, retrying in 10s...")
        time.sleep(10)
