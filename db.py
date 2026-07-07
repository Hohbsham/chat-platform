"""
SQLite database — the "notebook" that won't tear, lose pages, or let two people
write at the same time.

Replaces agents.json + tasks.json + messages.json with a single SQLite file.
"""
import sqlite3, json, os, time, uuid, threading

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "a2a.db")

_conn = None
_lock = threading.Lock()


def _get_conn():
    """Thread-safe connection. SQLite in WAL mode handles concurrent readers."""
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
        _create_tables(_conn)
    return _conn


def _create_tables(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS agents (
            agent_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            role TEXT DEFAULT '',
            goal TEXT DEFAULT '',
            backstory TEXT DEFAULT '',
            capabilities TEXT DEFAULT '[]',
            model TEXT DEFAULT '',
            status TEXT DEFAULT 'offline',
            current_task_id TEXT,
            registered_at REAL DEFAULT 0,
            last_seen REAL DEFAULT 0,
            verified INTEGER DEFAULT 0,
            source TEXT DEFAULT 'unknown'
        );

        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            creator TEXT DEFAULT 'Anonymous',
            required_capabilities TEXT DEFAULT '[]',
            priority TEXT DEFAULT 'normal',
            status TEXT DEFAULT 'pending',
            broadcast INTEGER DEFAULT 0,
            context TEXT DEFAULT '[]',
            max_rounds INTEGER DEFAULT 0,
            current_round INTEGER DEFAULT 0,
            speaker_queue TEXT DEFAULT '[]',
            assigned_to TEXT DEFAULT '',
            approval_required INTEGER DEFAULT 0,
            approved INTEGER DEFAULT 0,
            created_at REAL DEFAULT 0,
            claimed_by TEXT,
            claimed_at REAL,
            completed_by TEXT,
            completed_at REAL,
            result TEXT,
            error TEXT
        );

        CREATE TABLE IF NOT EXISTS task_responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            agent_name TEXT NOT NULL,
            result TEXT DEFAULT '',
            completed_at REAL DEFAULT 0,
            FOREIGN KEY (task_id) REFERENCES tasks(task_id)
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            type TEXT NOT NULL,
            sender TEXT NOT NULL,
            content TEXT NOT NULL,
            meta TEXT DEFAULT '{}'
        );

        CREATE INDEX IF NOT EXISTS idx_messages_ts ON messages(ts);
        CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
        CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);
    """)
    # Migration: add verified + source columns for existing databases
    try:
        conn.execute("ALTER TABLE agents ADD COLUMN verified INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # column already exists
    try:
        conn.execute("ALTER TABLE agents ADD COLUMN source TEXT DEFAULT 'unknown'")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE tasks ADD COLUMN assigned_to TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    conn.commit()


# ── Capability trust system ──────────────────────────────────────

# Capabilities that REQUIRE verification. Unverified agents claiming these
# will have them automatically downgraded or rejected.
TRUSTED_CAPABILITIES = {
    "database_access", "real_inspection", "file_operations",
    "shell_exec", "file_read", "file_write", "file_edit",
    "browser", "server_management", "blender_render",
    "memory", "skill_create", "subagent_spawn", "cron_schedule",
    "code_generation", "debugging", "refactoring",  # need real tools too
}

# Agents from these sources are automatically trusted
TRUSTED_SOURCES = {"hermes_agent", "quality_evaluator_agent", "custom", "bpt_data_check", "bpt_train", "claude-ide-window"}


def verify_capabilities(capabilities, verified, source):
    """
    Check claimed capabilities against trust level.
    Returns (trusted_caps, untrusted_caps_warning).
    """
    claimed = set(capabilities or [])
    trusted = claimed - TRUSTED_CAPABILITIES  # always allowed
    suspicious = claimed & TRUSTED_CAPABILITIES

    if verified:
        # Verified agent — all caps allowed
        return list(claimed), None

    if suspicious:
        # Unverified agent claiming trusted capabilities — downgrade
        return list(trusted), f"Agent from '{source}' is NOT verified. These capabilities require verification and have been removed: {', '.join(sorted(suspicious))}"

    return list(claimed), None


# ── JSON helpers ───────────────────────────────────────────────

def _to_json(val):
    return json.dumps(val, ensure_ascii=False)


def _from_json(text, default=None):
    if default is None:
        default = []
    try:
        return json.loads(text) if text else default
    except (json.JSONDecodeError, TypeError):
        return default


def _row_to_dict(row, extras=None):
    """Convert sqlite3.Row to plain dict, deserializing JSON fields."""
    d = dict(row) if row else {}
    # Deserialize known JSON fields
    for key in ("capabilities", "required_capabilities", "context",
                "speaker_queue", "meta", "responses"):
        if key in d and isinstance(d[key], str):
            d[key] = _from_json(d[key], [] if key != "meta" else {})
    if extras:
        d.update(extras)
    return d


# ── Agent Store ────────────────────────────────────────────────

AGENT_TIMEOUT = 999999  # Effectively infinite — agents never go "offline"


def agent_all():
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM agents").fetchall()
    return [_row_to_dict(r) for r in rows]


def agent_find(agent_id):
    conn = _get_conn()
    row = conn.execute("SELECT * FROM agents WHERE agent_id=?", (agent_id,)).fetchone()
    return _row_to_dict(row) if row else None


def agent_find_by_name_source(name, source):
    """Find existing agent with same name and source. Used for dedup on re-registration."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM agents WHERE name=? AND source=? ORDER BY last_seen DESC LIMIT 1",
        (name, source)).fetchone()
    return _row_to_dict(row) if row else None


def agent_register(agent_id, name, role="", goal="", backstory="",
                   capabilities=None, model="", verified=False, source="unknown"):
    now = time.time()
    existing = agent_find(agent_id)

    # Verify capabilities: strip trusted caps from unverified agents
    caps_list = capabilities or []
    trusted_caps, warning = verify_capabilities(caps_list, verified, source)

    conn = _get_conn()
    if existing:
        conn.execute("""
            UPDATE agents SET name=?, role=?, goal=?, backstory=?,
            capabilities=?, model=?, status='online', last_seen=?,
            verified=?, source=?
            WHERE agent_id=?
        """, (name, role or existing.get("role", ""),
              goal or existing.get("backstory", ""),
              backstory or existing.get("backstory", ""),
              _to_json(trusted_caps),
              model or existing.get("model", ""), now,
              1 if verified else 0, source,
              agent_id))
    else:
        conn.execute("""
            INSERT INTO agents (agent_id, name, role, goal, backstory,
            capabilities, model, status, registered_at, last_seen,
            verified, source)
            VALUES (?,?,?,?,?,?,?, 'online', ?, ?, ?, ?)
        """, (agent_id, name, role, goal, backstory,
              _to_json(trusted_caps), model, now, now,
              1 if verified else 0, source))
    conn.commit()
    return agent_find(agent_id), warning


def agent_heartbeat(agent_id):
    now = time.time()
    conn = _get_conn()
    conn.execute("UPDATE agents SET status='online', last_seen=? WHERE agent_id=?",
                 (now, agent_id))
    conn.commit()
    return agent_find(agent_id)


def agent_set_status(agent_id, status, task_id=None):
    now = time.time()
    conn = _get_conn()
    if task_id is not None:
        conn.execute("UPDATE agents SET status=?, last_seen=?, current_task_id=? WHERE agent_id=?",
                     (status, now, task_id, agent_id))
    else:
        conn.execute("UPDATE agents SET status=?, last_seen=? WHERE agent_id=?",
                     (status, now, agent_id))
    conn.commit()


def agent_unregister(agent_id):
    agent_set_status(agent_id, "offline")


def agent_cleanup_offline():
    """Mark timed-out agents as offline. Returns list of changed agents."""
    now = time.time()
    conn = _get_conn()
    cutoff = now - AGENT_TIMEOUT
    rows = conn.execute(
        "SELECT agent_id FROM agents WHERE status!='offline' AND last_seen < ?",
        (cutoff,)).fetchall()
    if rows:
        ids = [(r["agent_id"],) for r in rows]
        conn.executemany("UPDATE agents SET status='offline' WHERE agent_id=?", ids)
        conn.commit()
    return [r["agent_id"] for r in rows]


def agent_online():
    return [a for a in agent_all() if a["status"] != "offline"]


def agent_count():
    return _get_conn().execute("SELECT COUNT(*) as n FROM agents").fetchone()["n"]


# ── Task Store ─────────────────────────────────────────────────

TASK_STATUSES = ["pending", "claimed", "working", "input_required",
                 "completed", "failed", "cancelled"]


def task_all():
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC").fetchall()
    tasks = []
    for r in rows:
        t = _row_to_dict(r)
        # Attach responses
        resp_rows = conn.execute(
            "SELECT * FROM task_responses WHERE task_id=?", (t["task_id"],)).fetchall()
        t["responses"] = [_row_to_dict(rr, {}) for rr in resp_rows]
        tasks.append(t)
    return tasks


def task_find(task_id):
    conn = _get_conn()
    row = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
    if not row:
        return None
    t = _row_to_dict(row)
    resp_rows = conn.execute(
        "SELECT * FROM task_responses WHERE task_id=?", (task_id,)).fetchall()
    t["responses"] = [_row_to_dict(rr, {}) for rr in resp_rows]
    return t


def task_create(title, description="", required_capabilities=None,
                priority="normal", creator="Anonymous", broadcast=False,
                context=None, max_rounds=0, approval_required=False,
                assigned_to=""):
    task_id = f"task-{uuid.uuid4().hex[:8]}"
    now = time.time()
    conn = _get_conn()
    conn.execute("""
        INSERT INTO tasks (task_id, title, description, creator,
        required_capabilities, priority, status, broadcast, context,
        max_rounds, assigned_to, approval_required, created_at)
        VALUES (?,?,?,?,?,?, 'pending', ?,?,?,?,?,?)
    """, (task_id, title, description, creator,
          _to_json(required_capabilities or []), priority,
          1 if broadcast else 0, _to_json(context or []),
          max_rounds, assigned_to,
          1 if approval_required else 0, now))
    conn.commit()
    return task_find(task_id)


def task_update(task_id, **updates):
    """Update task fields. JSON-encodes list/dict values automatically."""
    conn = _get_conn()
    json_fields = {"required_capabilities", "context", "speaker_queue"}
    set_parts = []
    values = []
    for k, v in updates.items():
        if k in ("responses",):  # handled separately
            continue
        if k in json_fields and isinstance(v, (list, dict)):
            v = _to_json(v)
        # Convert bool to int for SQLite
        if isinstance(v, bool):
            v = 1 if v else 0
        set_parts.append(f"{k}=?")
        values.append(v)
    values.append(task_id)
    conn.execute(f"UPDATE tasks SET {', '.join(set_parts)} WHERE task_id=?", values)

    # Handle responses separately
    if "responses" in updates:
        conn.execute("DELETE FROM task_responses WHERE task_id=?", (task_id,))
        for r in updates["responses"]:
            if isinstance(r, dict):
                conn.execute("""
                    INSERT INTO task_responses (task_id, agent_id, agent_name, result, completed_at)
                    VALUES (?,?,?,?,?)
                """, (task_id, r.get("agent_id", ""), r.get("agent_name", ""),
                      r.get("result", ""), r.get("completed_at", 0)))

    conn.commit()
    return task_find(task_id)


def task_cancel_stale(agent_id):
    """Release tasks claimed by offline agent back to pending."""
    conn = _get_conn()
    conn.execute("""
        UPDATE tasks SET status='pending', claimed_by=NULL, claimed_at=NULL
        WHERE claimed_by=? AND status='claimed'
    """, (agent_id,))
    conn.commit()


# ── Message Store ───────────────────────────────────────────────

MAX_MESSAGES = 500


def message_all(since=0):
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM messages WHERE ts > ? ORDER BY ts ASC LIMIT 200",
        (since,)).fetchall()
    return [_row_to_dict(r, {}) for r in rows]


def message_append(msg_type, sender, content, meta=None):
    conn = _get_conn()
    ts = time.time()
    conn.execute("""
        INSERT INTO messages (ts, type, sender, content, meta)
        VALUES (?,?,?,?,?)
    """, (ts, msg_type, sender, content, _to_json(meta or {})))
    # Trim old messages
    count = conn.execute("SELECT COUNT(*) as n FROM messages").fetchone()["n"]
    if count > MAX_MESSAGES:
        conn.execute("""
            DELETE FROM messages WHERE id IN (
                SELECT id FROM messages ORDER BY ts ASC LIMIT ?
            )
        """, (count - MAX_MESSAGES,))
    conn.commit()
    # Return the inserted message
    row = conn.execute(
        "SELECT * FROM messages WHERE ts=? AND type=? AND sender=? ORDER BY id DESC LIMIT 1",
        (ts, msg_type, sender)).fetchone()
    return _row_to_dict(row, {})


def message_task_timeline(task_id):
    """Get all messages related to a task."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM messages WHERE json_extract(meta, '$.task_id') = ? ORDER BY ts ASC",
        (task_id,)).fetchall()
    return [_row_to_dict(r, {}) for r in rows]


# ── Health ──────────────────────────────────────────────────────

def db_health():
    """Check database integrity and return stats."""
    conn = _get_conn()
    return {
        "agents_total": conn.execute("SELECT COUNT(*) as n FROM agents").fetchone()["n"],
        "agents_online": conn.execute(
            "SELECT COUNT(*) as n FROM agents WHERE status!='offline'").fetchone()["n"],
        "tasks_pending": conn.execute(
            "SELECT COUNT(*) as n FROM tasks WHERE status='pending'").fetchone()["n"],
        "tasks_total": conn.execute("SELECT COUNT(*) as n FROM tasks").fetchone()["n"],
        "messages_total": conn.execute("SELECT COUNT(*) as n FROM messages").fetchone()["n"],
        "db_size_kb": round(os.path.getsize(DB_PATH) / 1024, 1) if os.path.exists(DB_PATH) else 0,
    }


# ── Evaluation Store ─────────────────────────────────────────────

MAX_EVALS = 500


def _create_eval_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS evaluations (
            eval_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            agent_name TEXT DEFAULT '',
            agent_role TEXT DEFAULT '',
            domain TEXT DEFAULT '',
            task_title TEXT DEFAULT '',
            timestamp REAL DEFAULT 0,
            scores TEXT DEFAULT '{}',
            evidence TEXT DEFAULT '[]',
            suggestions TEXT DEFAULT '[]',
            strengths TEXT DEFAULT '[]',
            weaknesses TEXT DEFAULT '[]',
            confidence REAL DEFAULT 0,
            flags TEXT DEFAULT '[]',
            stage1_checks TEXT DEFAULT '{}',
            judge_raw TEXT DEFAULT ''
        )
    """)


# Ensure eval table exists on import
_create_eval_table(_get_conn())


def eval_all(since=0):
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM evaluations WHERE timestamp > ? ORDER BY timestamp DESC LIMIT 200",
        (since,)).fetchall()
    return [_row_to_dict(r, {}) for r in rows]


def eval_find(eval_id):
    conn = _get_conn()
    row = conn.execute("SELECT * FROM evaluations WHERE eval_id=?", (eval_id,)).fetchone()
    return _row_to_dict(row, {}) if row else None


def eval_append(evaluation_dict):
    """Store an evaluation result."""
    conn = _get_conn()
    e = evaluation_dict
    conn.execute("""
        INSERT OR REPLACE INTO evaluations
        (eval_id, task_id, agent_id, agent_name, agent_role, domain, task_title,
         timestamp, scores, evidence, suggestions, strengths, weaknesses,
         confidence, flags, stage1_checks, judge_raw)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        e.get("eval_id", uuid.uuid4().hex[:12]),
        e.get("task_id", ""),
        e.get("agent_id", ""),
        e.get("agent_name", ""),
        e.get("agent_role", ""),
        e.get("domain", ""),
        e.get("task_title", ""),
        e.get("timestamp", time.time()),
        _to_json(e.get("scores", {})),
        _to_json(e.get("evidence", [])),
        _to_json(e.get("suggestions", [])),
        _to_json(e.get("strengths", [])),
        _to_json(e.get("weaknesses", [])),
        e.get("confidence", 0.0),
        _to_json(e.get("flags", [])),
        _to_json(e.get("stage1_checks", {})),
        e.get("judge_raw", ""),
    ))
    # Trim old
    count = conn.execute("SELECT COUNT(*) as n FROM evaluations").fetchone()["n"]
    if count > MAX_EVALS:
        conn.execute("DELETE FROM evaluations WHERE eval_id IN (SELECT eval_id FROM evaluations ORDER BY timestamp ASC LIMIT ?)",
                     (count - MAX_EVALS,))
    conn.commit()
    return eval_find(e.get("eval_id"))


def platform_overview():
    """Return platform-wide evaluation summary."""
    conn = _get_conn()
    total = conn.execute("SELECT COUNT(*) as n FROM evaluations").fetchone()["n"]
    if total == 0:
        return {"total_evaluations": 0, "platform_avg": 0, "domains": {}}
    avg_score = conn.execute(
        "SELECT AVG(json_extract(scores, '$.overall')) as avg FROM evaluations").fetchone()["avg"]
    by_domain = conn.execute("""
        SELECT domain, COUNT(*) as count,
        AVG(json_extract(scores, '$.overall')) as avg_score
        FROM evaluations GROUP BY domain
    """).fetchall()
    domains = {}
    for r in by_domain:
        domains[r["domain"]] = {"count": r["count"], "avg": round(r["avg_score"] or 0, 1)}
    return {
        "total_evaluations": total,
        "platform_avg": round(avg_score or 0, 1),
        "domains": domains,
    }


def eval_query(agent_id=None, agent_name=None, domain=None, limit=50):
    """Query evaluations with optional filters."""
    conn = _get_conn()
    conditions = []
    params = []
    if agent_id:
        conditions.append("agent_id=?")
        params.append(agent_id)
    if agent_name:
        conditions.append("agent_name=?")
        params.append(agent_name)
    if domain:
        conditions.append("domain=?")
        params.append(domain)
    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)
    rows = conn.execute(
        f"SELECT * FROM evaluations{where} ORDER BY timestamp DESC LIMIT ?",
        params).fetchall()
    return [_row_to_dict(r, {}) for r in rows]
