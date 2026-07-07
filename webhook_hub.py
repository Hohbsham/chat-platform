"""
Webhook Hub v2 — Lightweight notification broker.
Zero AI. Pure HTTP message relay. ~30MB RAM.

A2A Server fires webhook here → Hub stores → Agent claims & completes.

Run: python webhook_hub.py --port 8767
"""
import json, os, sys, time, threading
from http.server import HTTPServer, BaseHTTPRequestHandler

BASE = os.path.dirname(os.path.abspath(__file__))
STORE_FILE = os.path.join(BASE, "webhook_store.json")

LEASE_TIMEOUT = 300  # 5 min
_store = {}  # task_id → {task_id, title, agent, status, claimed_by, claimed_at, ...}
_lock = threading.Lock()


def _load():
    global _store
    try:
        if os.path.exists(STORE_FILE):
            with open(STORE_FILE, "r") as f:
                _store = json.load(f)
    except Exception:
        _store = {}


def _save():
    with _lock:
        with open(STORE_FILE, "w") as f:
            json.dump(_store, f, indent=2)


def _expire():
    now = time.time()
    changed = False
    for t in list(_store.values()):
        if t.get("status") == "claimed" and (now - t.get("claimed_at", 0)) > LEASE_TIMEOUT:
            t["status"] = "pending"
            t["claimed_by"] = None
            t["claimed_at"] = 0
            changed = True
    if changed:
        _save()


_load()  # restore from disk on startup


class HubHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code, body):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 0 and length < 100_000:
                return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            pass
        return {}

    def log_message(self, *args):
        pass  # silent

    def do_GET(self):
        p = self.path.rstrip("/")
        _expire()
        if p == "/health":
            with _lock:
                counts = {"pending": 0, "claimed": 0, "total": len(_store)}
                for t in _store.values():
                    s = t.get("status", "?")
                    counts[s] = counts.get(s, 0) + 1
            # Overflow guard: if inbox piles up, worker is dead
            inbox_dir = os.path.join(BASE, "inbox")
            inbox_count = len([f for f in os.listdir(inbox_dir) if f.endswith(".json")]) if os.path.exists(inbox_dir) else 0
            alert = None
            if inbox_count > 10:
                alert = f"WORKER_DOWN: {inbox_count} files in inbox — Claude may be offline"
            self._send(200, {"ok": True, "service": "webhook-hub",
                "stats": counts, "inbox_depth": inbox_count,
                "alert": alert})
        elif p == "/pending":
            with _lock:
                tasks = list(_store.values())
            self._send(200, tasks)
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        p = self.path.rstrip("/")
        data = self._read_body()
        _expire()

        if p == "/webhook":
            tid = data.get("task_id", "") or f"task-{time.time()}"
            with _lock:
                _store[tid] = {
                    "task_id": tid, "title": data.get("title", "Untitled"),
                    "agent": data.get("agent", ""), "status": "pending",
                    "claimed_by": None, "claimed_at": 0,
                    "created_at": time.time(),
                }
            _save()
            # Atomic write to inbox: tmp → rename, Claude never sees half-written file
            inbox_dir = os.path.join(BASE, "inbox")
            os.makedirs(inbox_dir, exist_ok=True)
            tmp_path = os.path.join(inbox_dir, f"{tid}.json.tmp")
            final_path = os.path.join(inbox_dir, f"{tid}.json")
            try:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(_store[tid], f, ensure_ascii=False)
                os.replace(tmp_path, final_path)  # atomic on Windows & POSIX
            except Exception:
                pass
            # Desktop notification
            try:
                agent = data.get("agent", "")
                title = data.get("title", "")[:100]
                import subprocess
                subprocess.Popen(
                    f'powershell -Command "Add-Type -AssemblyName System.Windows.Forms; '
                    f'$n=New-Object System.Windows.Forms.NotifyIcon; '
                    f'$n.Icon=[System.Drawing.SystemIcons]::Information; '
                    f'$n.BalloonTipTitle=\\\"A2A Task for {agent}\\\"; '
                    f'$n.BalloonTipText=\\\"{title}\\\"; '
                    f'$n.Visible=\\\$true; $n.ShowBalloonTip(3000); Start-Sleep -Seconds 3; $n.Dispose()"',
                    shell=True,
                    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
                )
            except Exception:
                pass
            self._send(200, {"ok": True, "task_id": tid, "status": "pending"})

        elif p == "/claim":
            tid = data.get("task_id", "")
            agent_id = data.get("agent_id", "unknown")
            with _lock:
                t = _store.get(tid)
                if not t:
                    self._send(404, {"ok": False, "msg": "NOT_FOUND"})
                    return
                if t["status"] != "pending":
                    self._send(409, {"ok": False, "msg": f"ALREADY_{t['status'].upper()}"})
                    return
                t["status"] = "claimed"
                t["claimed_by"] = agent_id
                t["claimed_at"] = time.time()
            _save()
            self._send(200, {"ok": True, "msg": "CLAIMED"})

        elif p == "/done":
            tid = data.get("task_id", "")
            with _lock:
                t = _store.pop(tid, None)
            _save()
            if t:
                self._send(200, {"ok": True, "detail": {"task_id": tid, "agent": t.get("agent"), "title": t.get("title")}})
            else:
                self._send(404, {"ok": False, "msg": "NOT_FOUND"})

        else:
            self._send(404, {"error": "not found"})


def main():
    PORT = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[1] == "--port" else 8767
    server = HTTPServer(("0.0.0.0", PORT), HubHandler)
    print(f"  Webhook Hub v2 :{PORT}  |  Lease: {LEASE_TIMEOUT}s  |  Store: {STORE_FILE}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
