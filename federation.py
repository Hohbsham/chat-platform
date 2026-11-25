# -*- coding: utf-8 -*-
"""A2A Federation — 让「别人的 agent」通过一个网络地址接入本平台。

设计要点（为什么这么设计）：

1. **拉模式，不是推模式。**
   别人的 agent 在自己家/学校的 NAT 后面，我们主动连不进去。所以平台只提供
   `GET /api/federation/events?since=N`：每个 agent 自己记着看到第几条，来拉新的。
   平台不关心它在哪、是不是在线、有没有公网 IP。

2. **资料柜（artifact）而不是消息体。**
   报告、图片、数据落在服务器上，按内容哈希命名；事件里只放 id 和标题。
   消息体可以很小，重传/去重都简单。

3. **身份：邀请码 → token。**
   邀请码（invite key）只给你信任的人；他用它换一枚 token。之后所有写操作和
   读事件都要带 `Authorization: Bearer <token>`。
   本机（127.0.0.1）免 token —— 这样原来那 11 个本机 agent 一行都不用改。

4. **不碰原来的 a2a.db。**
   联邦数据单独一个 `federation.db`，schema 独立；注册的 agent 额外镜像进
   主库，好在原来的 UI 里看到。

挂载方式：server.py 的 handle_http 开头先问一句 `federation.route(...)`，
它认领 /api/federation/* 和 /api/artifacts/*，其余原样交还给平台。
"""
import hashlib
import json
import os
import secrets
import sqlite3
import threading
import time
import urllib.request
import urllib.parse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "federation.db")
STORE = os.path.join(BASE_DIR, "federation_store", "artifacts")
INVITE_FILE = os.path.join(BASE_DIR, "federation_invite.txt")
MAX_ARTIFACT_BYTES = 32 * 1024 * 1024      # 32 MB 上限，够放报告和图
KINDS_DEFAULT = ["report", "image", "data", "log", "note"]

_lock = threading.Lock()
_conn = None


# ─────────────────────────── 存储层 ───────────────────────────

def _db():
    global _conn
    if _conn is None:
        os.makedirs(STORE, exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript("""
        CREATE TABLE IF NOT EXISTS agents_ext (
            agent_id    TEXT PRIMARY KEY,
            name        TEXT,
            owner       TEXT,
            role        TEXT,
            capabilities TEXT,
            notify_mode TEXT,          -- poll | webhook | signal
            webhook_url TEXT,
            token_hash  TEXT,
            created     REAL,
            last_seen   REAL,
            last_seq    INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS events (
            seq         INTEGER PRIMARY KEY AUTOINCREMENT,
            type        TEXT,
            actor       TEXT,
            artifact_id TEXT,
            title       TEXT,
            payload     TEXT,
            ts          REAL
        );
        CREATE TABLE IF NOT EXISTS artifacts (
            id       TEXT PRIMARY KEY,
            sha256   TEXT,
            name     TEXT,
            kind     TEXT,
            author   TEXT,
            size     INTEGER,
            path     TEXT,
            ts       REAL
        );
        CREATE TABLE IF NOT EXISTS subs (
            agent_id TEXT,
            kind     TEXT
        );
        """)
        _conn.commit()
    return _conn


def invite_key():
    """邀请码：只发给信任的人。第一次启动自动生成。"""
    if not os.path.exists(INVITE_FILE):
        with open(INVITE_FILE, "w", encoding="utf-8") as f:
            f.write(secrets.token_urlsafe(12) + "\n")
    with open(INVITE_FILE, "r", encoding="utf-8") as f:
        return f.read().strip()


def _hash(tok):
    return hashlib.sha256(tok.encode("utf-8")).hexdigest()


# ─────────────────────────── 事件 ───────────────────────────

def publish(etype, actor, title, artifact_id=None, extra=None):
    """写一条事件，并按订阅尽力推给 webhook 型 agent（推不到不影响主流程）。"""
    with _lock:
        c = _db()
        cur = c.execute(
            "INSERT INTO events (type, actor, artifact_id, title, payload, ts)"
            " VALUES (?,?,?,?,?,?)",
            (etype, actor, artifact_id, title,
             json.dumps(extra or {}, ensure_ascii=False), time.time()))
        c.commit()
        seq = cur.lastrowid
        rows = c.execute("SELECT * FROM agents_ext WHERE notify_mode='webhook'"
                         " AND webhook_url IS NOT NULL AND webhook_url<>''").fetchall()

    ev = {"seq": seq, "type": etype, "actor": actor, "title": title,
          "artifact_id": artifact_id, "extra": extra or {}, "ts": time.time()}
    for r in rows:
        if not _subscribed(_db(), r["agent_id"], etype):
            continue
        try:
            body = json.dumps(ev, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                r["webhook_url"], data=body,
                headers={"Content-Type": "application/json",
                         "X-A2A-Event-Seq": str(seq)})
            urllib.request.urlopen(req, timeout=3).read()
        except Exception:
            pass        # 对方没开/推不到，等它下次来拉
    return ev


def _subscribed(conn, agent_id, etype):
    rows = conn.execute("SELECT kind FROM subs WHERE agent_id=?", (agent_id,)).fetchall()
    if not rows:
        return True          # 没订阅 = 全收
    kinds = {r["kind"] for r in rows}
    return "*" in kinds or etype in kinds


def events_since(agent_id, since, limit=50, mark_read=False):
    c = _db()
    rows = c.execute("SELECT * FROM events WHERE seq > ? ORDER BY seq ASC LIMIT ?",
                     (since, limit)).fetchall()
    out = []
    for r in rows:
        if not _subscribed(c, agent_id, r["type"]):
            continue
        e = dict(r)
        e["extra"] = json.loads(e.get("payload") or "{}")
        e.pop("payload", None)
        if e.get("artifact_id"):
            a = c.execute("SELECT id,name,kind,size,author,sha256 FROM artifacts WHERE id=?",
                          (e["artifact_id"],)).fetchone()
            e["artifact"] = dict(a) if a else None
        out.append(e)
    if mark_read and rows:
        c.execute("UPDATE agents_ext SET last_seq=?, last_seen=? WHERE agent_id=?",
                  (rows[-1]["seq"], time.time(), agent_id))
        c.commit()
    return out


# ─────────────────────────── 身份 ───────────────────────────

def agent_by_token(tok):
    if not tok:
        return None
    row = _db().execute("SELECT * FROM agents_ext WHERE token_hash=?",
                        (_hash(tok),)).fetchone()
    return dict(row) if row else None


def _auth(headers, client_ip):
    """本机免 token（兼容原来的 11 个 agent）；远端必须 Bearer。"""
    auth = (headers or {}).get("authorization", "")
    tok = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if tok:
        a = agent_by_token(tok)
        if a:
            return a
        return None
    if client_ip in ("127.0.0.1", "::1", "localhost"):
        return {"agent_id": "local", "name": "localhost", "owner": "host",
                "notify_mode": "poll", "local": True}
    return None


def join(payload):
    """别人的 agent 注册入口：邀请码 + 自报名字/能力 → 发一枚 token。"""
    if str(payload.get("invite_key", "")).strip() != invite_key():
        return None, "邀请码不对"
    name = str(payload.get("name", "")).strip()
    if not name:
        return None, "必须有 name"
    owner = str(payload.get("owner", "")).strip()
    # 同一个 owner 的同名 agent 重复加入 → 换 token，不重复建
    agent_id = "ext-" + hashlib.sha1((owner + "/" + name).encode()).hexdigest()[:8]
    tok = secrets.token_urlsafe(24)
    now = time.time()
    c = _db()
    c.execute("""INSERT INTO agents_ext
        (agent_id,name,owner,role,capabilities,notify_mode,webhook_url,token_hash,created,last_seen)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(agent_id) DO UPDATE SET
            name=excluded.name, owner=excluded.owner, role=excluded.role,
            capabilities=excluded.capabilities, notify_mode=excluded.notify_mode,
            webhook_url=excluded.webhook_url, token_hash=excluded.token_hash,
            last_seen=excluded.last_seen""",
        (agent_id, name, owner, payload.get("role", ""),
         json.dumps(payload.get("capabilities", []), ensure_ascii=False),
         payload.get("notify_mode", "poll"), payload.get("webhook_url", ""),
         _hash(tok), now, now))
    c.commit()

    # 镜像进主库，好在原来的平台 UI 里看见
    try:
        import db as a2a_db
        a2a_db.agent_register(agent_id, name, role=payload.get("role", ""),
                              goal=payload.get("goal", ""),
                              backstory=payload.get("backstory", ""),
                              capabilities=payload.get("capabilities", []),
                              model=payload.get("model", ""),
                              verified=True, source="federation:" + (owner or "?"))
    except Exception:
        pass

    publish("agent.joined", name, f"{name} 加入了平台（owner={owner or '未填'}）",
            extra={"agent_id": agent_id, "notify_mode": payload.get("notify_mode", "poll")})
    return {"agent_id": agent_id, "name": name, "token": tok}, None


# ─────────────────────────── 资料柜 ───────────────────────────

def put_artifact(body, name, kind, title, author, tags=None):
    if len(body) > MAX_ARTIFACT_BYTES:
        return None, "文件超过 32 MB"
    sha = hashlib.sha256(body).hexdigest()
    aid = "art-" + sha[:12]
    d = os.path.join(STORE, sha[:2])
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, sha)
    if not os.path.exists(path):
        with open(path, "wb") as f:
            f.write(body)
    with _lock:
        c = _db()
        c.execute("INSERT OR REPLACE INTO artifacts (id,sha256,name,kind,author,size,path,ts)"
                  " VALUES (?,?,?,?,?,?,?,?)",
                  (aid, sha, name, kind, author, len(body), path, time.time()))
        c.commit()
    publish("artifact.created", author, title or name, aid,
            extra={"kind": kind, "name": name, "size": len(body),
                   "tags": tags or []})
    return {"artifact_id": aid, "sha256": sha, "size": len(body), "url": "/api/artifacts/" + aid}, None


def get_artifact(aid):
    return _db().execute("SELECT * FROM artifacts WHERE id=?", (aid,)).fetchone()


def roster():
    rows = _db().execute("SELECT agent_id,name,owner,role,capabilities,notify_mode,"
                         "last_seen FROM agents_ext ORDER BY name").fetchall()
    return [dict(r) for r in rows]


# ─────────────────────────── 路由 ───────────────────────────

def _j(obj, status=200):
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    return status, {"Content-Type": "application/json; charset=utf-8",
                    "Access-Control-Allow-Origin": "*"}, body


def route(path, method, query, body_bytes, headers=None, client_ip=None):
    """认领联邦相关路径；不认识的返回 None，交回给平台原路由。"""
    if not (path.startswith("/api/federation") or path.startswith("/api/artifacts")):
        return None

    headers = headers or {}

    # 公开：加入 + 健康
    if path == "/api/federation/info":
        return _j({"ok": True, "platform": "a2a-federation", "version": 1,
                   "kinds": KINDS_DEFAULT, "agents": len(roster()),
                   "hint": "POST /api/federation/join 用邀请码换 token"})

    if path == "/api/federation/join" and method == "POST":
        try:
            payload = json.loads(body_bytes.decode("utf-8") or "{}")
        except Exception:
            return _j({"ok": False, "error": "body 不是 JSON"}, 400)
        data, err = join(payload)
        if err:
            return _j({"ok": False, "error": err}, 401)
        return _j({"ok": True, **data})

    me = _auth(headers, client_ip)
    if not me:
        return _j({"ok": False, "error": "需要 Authorization: Bearer <token>"}, 401)

    if path == "/api/federation/whoami":
        return _j({"ok": True, "agent": {k: me.get(k) for k in
                                         ("agent_id", "name", "owner", "notify_mode")}})

    if path == "/api/federation/roster":
        return _j({"ok": True, "agents": roster()})

    if path == "/api/federation/events":
        since = int((query.get("since", ["0"])[0]) or 0)
        limit = min(int((query.get("limit", ["50"])[0]) or 50), 200)
        mark = (query.get("ack", ["0"])[0] in ("1", "true"))
        evs = events_since(me.get("agent_id", "local"), since, limit, mark_read=mark)
        return _j({"ok": True, "since": since, "events": evs,
                   "next": evs[-1]["seq"] if evs else since})

    if path == "/api/federation/subscribe" and method == "POST":
        try:
            payload = json.loads(body_bytes.decode("utf-8") or "{}")
        except Exception:
            payload = {}
        kinds = payload.get("kinds") or ["*"]
        c = _db()
        c.execute("DELETE FROM subs WHERE agent_id=?", (me["agent_id"],))
        for k in kinds:
            c.execute("INSERT INTO subs (agent_id, kind) VALUES (?,?)", (me["agent_id"], k))
        c.commit()
        return _j({"ok": True, "subscribed": kinds})

    if path == "/api/federation/ack" and method == "POST":
        try:
            payload = json.loads(body_bytes.decode("utf-8") or "{}")
        except Exception:
            payload = {}
        seq = int(payload.get("seq", 0))
        c = _db()
        c.execute("UPDATE agents_ext SET last_seq=?, last_seen=? WHERE agent_id=?",
                  (seq, time.time(), me["agent_id"]))
        c.commit()
        return _j({"ok": True, "seq": seq})

    if path == "/api/artifacts" and method == "POST":
        # 元数据优先走 query（HTTP 头只能放 latin-1，中文标题必须走 URL 编码）
        def _q(k, default=""):
            v = query.get(k)
            return v[0] if v else default
        name = _q("name") or headers.get("x-filename") or "unnamed.txt"
        kind = _q("kind") or headers.get("x-kind") or "note"
        title = _q("title") or headers.get("x-title") or name
        tags = [t for t in (_q("tags") or headers.get("x-tags") or "").split(",") if t]
        author = me.get("name") or me.get("agent_id")
        data, err = put_artifact(body_bytes, name, kind, title, author, tags)
        if err:
            return _j({"ok": False, "error": err}, 400)
        return _j({"ok": True, **data})

    if path.startswith("/api/artifacts/") and method == "GET":
        aid = path.split("/api/artifacts/", 1)[1].strip("/")
        row = get_artifact(aid)
        if not row:
            return _j({"ok": False, "error": "没有这个 artifact"}, 404)
        with open(row["path"], "rb") as f:
            body = f.read()
        return 200, {"Content-Type": "application/octet-stream",
                     "Content-Disposition": 'attachment; filename="%s"' % row["name"],
                     "X-Sha256": row["sha256"],
                     "Access-Control-Allow-Origin": "*"}, body

    return _j({"ok": False, "error": "unknown federation route"}, 404)
