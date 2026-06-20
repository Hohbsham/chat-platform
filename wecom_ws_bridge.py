"""
WeCom AI Bot <-> A2A WebSocket Bridge
=====================================
Connects to WeCom AI Bot via WebSocket (long connection), forwards messages to
A2A platform, and sends task results back to WeCom users.

Protocol: WeCom AI Bot WebSocket (nested cmd/headers/body JSON)
Requires: pip install websockets
Usage:   python wecom_ws_bridge.py
"""
import asyncio
import json
import os
import sys
import time
import uuid
import urllib.request
import traceback

try:
    import websockets
except ImportError:
    print("ERROR: pip install websockets")
    sys.exit(1)

# ── Config ────────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

_env_path = os.path.join(BASE_DIR, ".env")
if os.path.exists(_env_path):
    with open(_env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

WECOM_BOT_ID = os.environ.get("WECOM_BOT_ID", "")
WECOM_SECRET = os.environ.get("WECOM_SECRET", "")
WECOM_WS_URL = os.environ.get("WECOM_WS_URL", "wss://openws.work.weixin.qq.com")
A2A_HOST = os.environ.get("CHAT_HOST", "http://localhost:8765")

BRIDGE_NAME = "WeCom-Bridge"
BRIDGE_AGENT_ID = f"{BRIDGE_NAME}-{uuid.uuid4().hex[:6]}"

# ── A2A API helpers ────────────────────────────────────────────────

def a2a_post(path, data):
    url = f"{A2A_HOST}{path}"
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body,
        headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=10).read())
    except Exception as e:
        return {"ok": False, "error": str(e)}

def a2a_get(path):
    try:
        return json.loads(urllib.request.urlopen(f"{A2A_HOST}{path}", timeout=10).read())
    except Exception:
        return []

def forward_to_a2a(user_name: str, content: str):
    """Forward WeCom message to A2A chat."""
    return a2a_post("/api/send", {
        "sender": f"{user_name}(WX)",
        "content": content,
    })

def register_bridge():
    return a2a_post("/api/agents/register", {
        "agent_id": BRIDGE_AGENT_ID,
        "name": BRIDGE_NAME,
        "role": "WeCom Message Bridge",
        "goal": "Relay messages between WeCom and A2A platform",
        "backstory": "Gateway agent connecting enterprise WeChat to A2A ecosystem.",
        "capabilities": ["chat", "notification"],
        "model": "",
    })

# ── WeCom Protocol ─────────────────────────────────────────────────

class WeComBridge:
    """WebSocket client for WeCom AI Bot (long-connection mode)."""

    def __init__(self, bot_id, secret, ws_url=WECOM_WS_URL):
        self.bot_id = bot_id
        self.secret = secret
        self.ws_url = ws_url
        self.device_id = uuid.uuid4().hex
        self.ws = None
        self.running = False
        self._pending = {}   # req_id -> Future
        self._last_wecom_user = None  # Latest WeCom user for reply routing

    @staticmethod
    def _new_req_id(prefix="req"):
        return f"{prefix}-{uuid.uuid4().hex}"

    @staticmethod
    def _req_id_of(payload):
        h = payload.get("headers")
        return h.get("req_id", "") if isinstance(h, dict) else ""

    def _make_frame(self, cmd, body=None):
        return {
            "cmd": cmd,
            "headers": {"req_id": self._new_req_id(cmd.replace("aibot_", ""))},
            "body": body or {},
        }

    async def connect(self):
        """Connect and authenticate."""
        print(f"[WeCom] Connecting to {self.ws_url}...")
        self.ws = await websockets.connect(
            self.ws_url,
            ping_interval=None,
            close_timeout=10,
        )
        print("[WeCom] WebSocket connected. Authenticating...")

        # ── Subscribe ──
        req_id = self._new_req_id("subscribe")
        sub = {
            "cmd": "aibot_subscribe",
            "headers": {"req_id": req_id},
            "body": {
                "bot_id": self.bot_id,
                "secret": self.secret,
                "device_id": self.device_id,
            },
        }
        await self.ws.send(json.dumps(sub, ensure_ascii=False))

        # Wait for auth response (matched by req_id)
        deadline = time.time() + 15
        while time.time() < deadline:
            raw = await asyncio.wait_for(self.ws.recv(), timeout=deadline - time.time())
            payload = json.loads(raw)
            if payload.get("cmd") == "ping":
                continue
            if self._req_id_of(payload) == req_id:
                errcode = payload.get("errcode", -1)
                if errcode == 0:
                    print("[WeCom] Auth OK -- listening for messages")
                    return True
                else:
                    errmsg = payload.get("errmsg", "unknown error")
                    print(f"[WeCom] Auth FAILED: errcode={errcode} {errmsg}")
                    return False
            # Ignore other pre-auth messages

        print("[WeCom] Auth timeout")
        return False

    async def send_message(self, user_id: str, content: str):
        """Send markdown message back to WeCom user."""
        if not self.ws:
            return False
        frame = self._make_frame("aibot_send_msg", {
            "msgid": uuid.uuid4().hex,
            "touser": user_id,
            "content": content,
            "msgtype": "markdown",
        })
        try:
            await self.ws.send(json.dumps(frame, ensure_ascii=False))
            return True
        except Exception as e:
            print(f"[WeCom] Send error: {e}")
            return False

    async def send_typing(self, user_id: str):
        if not self.ws:
            return
        frame = self._make_frame("aibot_sendtyping", {"touser": user_id})
        try:
            await self.ws.send(json.dumps(frame, ensure_ascii=False))
        except Exception:
            pass

    async def listen(self):
        """Main loop: connect, listen, reconnect."""
        self.running = True
        backoff = 2

        while self.running:
            try:
                ok = await self.connect()
                if not ok:
                    print(f"[WeCom] Retrying in {backoff}s...")
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 60)
                    continue

                backoff = 2  # reset on success
                # Start reply polling
                reply_task = asyncio.create_task(self._reply_poll_loop())

                # ── Message loop ──
                while self.running:
                    try:
                        raw = await asyncio.wait_for(self.ws.recv(), timeout=45)
                    except asyncio.TimeoutError:
                        # Send ping to keep alive
                        try:
                            ping = self._make_frame("ping")
                            await self.ws.send(json.dumps(ping, ensure_ascii=False))
                        except Exception:
                            break
                        continue

                    payload = json.loads(raw)
                    cmd = payload.get("cmd", "")

                    if cmd == "ping":
                        pong = self._make_frame("ping")
                        await self.ws.send(json.dumps(pong, ensure_ascii=False))
                        continue

                    if cmd in ("aibot_msg_callback", "aibot_callback"):
                        await self._handle_callback(payload)

                    elif cmd == "aibot_event_callback":
                        body = payload.get("body", {})
                        etype = body.get("eventtype", "")
                        print(f"[WeCom] Event: {etype}")

                    else:
                        # Could be response to our send, etc.
                        pass

            except websockets.ConnectionClosed:
                print(f"[WeCom] Disconnected -- reconnecting in {backoff}s...")
            except Exception as e:
                print(f"[WeCom] Error: {e}")
                traceback.print_exc()

            if self.running:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def _reply_poll_loop(self):
        """Poll A2A for replies and forward to WeCom."""
        last_ts = time.time()
        while self.running:
            try:
                msgs = a2a_get(f"/api/messages?since={last_ts}")
                for m in msgs:
                    ts = m.get("ts", 0)
                    if ts > last_ts:
                        last_ts = ts
                    sender = m.get("sender", "")
                    mtype = m.get("type", "")
                    content = m.get("content", "")
                    # Forward agent replies to WeCom (not user messages, not bridge echoes)
                    if sender in ("WeCom-Bridge", BRIDGE_NAME):
                        continue
                    if "(WX)" in sender:  # User's own message, don't echo
                        continue
                    if mtype in ("task_complete", "task_fail", "chat"):
                        if self._last_wecom_user:
                            label = {"task_complete": "完成", "task_fail": "失败"}.get(mtype, "")
                            prefix = f"[{label}] {sender}: " if label else f"{sender}: "
                            await self.send_message(self._last_wecom_user, prefix + content[:1000])
            except Exception:
                pass
            await asyncio.sleep(3)

    async def _handle_callback(self, payload: dict):
        """Process incoming message from WeCom user."""
        body = payload.get("body", {})
        msgtype = body.get("msgtype", "text")
        from_info = body.get("from", {})
        from_user = from_info.get("userid", "unknown")
        from_name = from_info.get("name", from_user)
        self._last_wecom_user = from_user  # Track for reply routing

        # Extract text
        content = ""
        if msgtype == "text":
            content = body.get("text", {}).get("content", "")
        elif msgtype == "image":
            content = "[图片]"
        elif msgtype == "voice":
            content = "[语音]"
        elif msgtype == "file":
            content = f"[文件: {body.get('file', {}).get('filename', '')}]"
        elif msgtype == "mixed":
            items = body.get("mixed", {}).get("msg_item", [])
            content = "".join(
                i.get("text", {}).get("content", "")
                for i in items if i.get("msgtype") == "text"
            )
        else:
            content = f"[{msgtype}]"

        if not content.strip():
            return

        print(f"[WeCom] {from_name}: {content[:100]}")

        # Forward to A2A chat
        forward_to_a2a(from_name, content)

        # Quick ack
        await self.send_typing(from_user)
        await asyncio.sleep(0.3)

        agents = a2a_get("/api/agents")
        online = [a.get("name", "") for a in agents if a.get("status") == "online"]

        if "OpenClaw" in online or "Hermes" in online:
            await self.send_message(from_user,
                f"收到，已分配专家处理中...\n\n> {content[:200]}"
            )
        else:
            await self.send_message(from_user,
                f"已收到你的消息。专家团队当前离线，消息已记录。\n\n> {content[:200]}"
            )

    async def stop(self):
        self.running = False
        if self.ws:
            await self.ws.close()

# ── Main ───────────────────────────────────────────────────────────

async def main():
    import argparse
    p = argparse.ArgumentParser(description="WeCom <-> A2A WebSocket Bridge")
    p.add_argument("--a2a-host", default=A2A_HOST, help="A2A platform URL")
    p.add_argument("--bot-id", default=WECOM_BOT_ID)
    p.add_argument("--secret", default=WECOM_SECRET)
    args = p.parse_args()

    # Update module-level configs
    import wecom_ws_bridge as self_mod
    self_mod.A2A_HOST = args.a2a_host
    self_mod.WECOM_BOT_ID = args.bot_id
    self_mod.WECOM_SECRET = args.secret

    print("=" * 60)
    print("  WeCom AI Bot <-> A2A Bridge")
    print("=" * 60)
    print(f"  A2A:     {A2A_HOST}")
    print(f"  Bot ID:  {WECOM_BOT_ID[:16] if WECOM_BOT_ID else 'NOT SET'}...")
    print(f"  Secret:  {'*' * 10}")
    print()

    # Register on A2A
    result = register_bridge()
    if result.get("ok"):
        agent = result.get("agent", {})
        print(f"[A2A] Registered as {agent.get('agent_id', BRIDGE_AGENT_ID)}")
    else:
        print(f"[A2A] Register: {result}")

    bridge = WeComBridge(WECOM_BOT_ID, WECOM_SECRET)
    try:
        await bridge.listen()
    except KeyboardInterrupt:
        print("\n[WeCom] Shutting down...")
        await bridge.stop()

if __name__ == "__main__":
    asyncio.run(main())
