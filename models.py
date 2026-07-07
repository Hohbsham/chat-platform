"""
Data models for A2A Chat Platform v2.
Agent identity (CrewAI-inspired) + Task state machine (A2A-inspired).
"""
import json, os, time, uuid, threading
from dataclasses import dataclass, field, asdict
from typing import Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Persistence helpers ──────────────────────────────────────────

_save_locks = {}  # path → Lock for per-file thread safety

def _get_lock(path):
    if path not in _save_locks:
        _save_locks[path] = threading.Lock()
    return _save_locks[path]

def _load(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        # Auto-backup corrupted file
        corrupted = path + ".corrupted." + time.strftime("%Y%m%d_%H%M%S")
        try:
            os.rename(path, corrupted)
        except Exception:
            pass
        return default

def _save(path, data):
    """Atomic write: tmp file → os.replace. Guarantees no corruption."""
    tmp = path + ".tmp"
    with _get_lock(path):
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

# ── Agent Model (CrewAI-inspired identity) ──────────────────────

@dataclass
class Agent:
    agent_id: str
    name: str
    role: str = ""           # e.g. "Senior Code Reviewer"
    goal: str = ""            # e.g. "Find security bugs and logic errors"
    backstory: str = ""       # e.g. "15 years of experience in secure code review..."
    capabilities: list = field(default_factory=list)
    model: str = ""           # AI model used by this agent
    status: str = "offline"   # offline | online | busy
    registered_at: float = 0.0
    last_seen: float = 0.0
    current_task_id: Optional[str] = None

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def from_dict(d):
        return Agent(
            agent_id=d.get("agent_id", ""),
            name=d.get("name", ""),
            role=d.get("role", ""),
            goal=d.get("goal", ""),
            backstory=d.get("backstory", ""),
            capabilities=d.get("capabilities", []),
            model=d.get("model", ""),
            status=d.get("status", "offline"),
            registered_at=d.get("registered_at", 0.0),
            last_seen=d.get("last_seen", 0.0),
            current_task_id=d.get("current_task_id"),
        )


class AgentStore:
    AGENT_TIMEOUT = 60

    def __init__(self, path=None):
        self.path = path or os.path.join(BASE_DIR, "agents.json")

    def all(self):
        return [Agent.from_dict(d) for d in _load(self.path, [])]

    def find(self, agent_id):
        for a in self.all():
            if a.agent_id == agent_id:
                return a
        return None

    def find_by_name(self, name):
        return [a for a in self.all() if a.name == name]

    def save(self, agent):
        agents = [a.to_dict() for a in self.all()]
        for i, a in enumerate(agents):
            if a["agent_id"] == agent.agent_id:
                agents[i] = agent.to_dict()
                _save(self.path, agents)
                return agent
        agents.append(agent.to_dict())
        _save(self.path, agents)
        return agent

    def register(self, agent_id, name, role="", goal="", backstory="",
                 capabilities=None, model=""):
        now = time.time()
        existing = self.find(agent_id)
        if existing:
            existing.name = name
            existing.role = role or existing.role
            existing.goal = goal or existing.goal
            existing.backstory = backstory or existing.backstory
            existing.capabilities = capabilities or existing.capabilities
            existing.model = model or existing.model
            existing.status = "online"
            existing.last_seen = now
            return self.save(existing)
        agent = Agent(
            agent_id=agent_id, name=name, role=role, goal=goal,
            backstory=backstory, capabilities=capabilities or [],
            model=model, status="online", registered_at=now, last_seen=now
        )
        return self.save(agent)

    def heartbeat(self, agent_id):
        agent = self.find(agent_id)
        if agent:
            agent.status = "online"
            agent.last_seen = time.time()
            return self.save(agent)
        return None

    def set_status(self, agent_id, status, task_id=None):
        agent = self.find(agent_id)
        if agent:
            agent.status = status
            agent.last_seen = time.time()
            if task_id is not None:
                agent.current_task_id = task_id
            return self.save(agent)
        return None

    def unregister(self, agent_id):
        return self.set_status(agent_id, "offline")

    def cleanup_offline(self):
        now = time.time()
        changed = []
        for a in self.all():
            if a.status != "offline" and (now - a.last_seen) > self.AGENT_TIMEOUT:
                a.status = "offline"
                self.save(a)
                changed.append(a)
        return changed

    def online_agents(self):
        return [a for a in self.all() if a.status != "offline"]

    def count(self):
        return len(self.all())


# ── Task Model (A2A-inspired state machine) ─────────────────────

# States: pending → claimed → working → input_required → completed / failed / cancelled
TASK_STATES = ["pending", "claimed", "working", "input_required",
               "completed", "failed", "cancelled"]
TERMINAL_STATES = {"completed", "failed", "cancelled"}

@dataclass
class TaskResponse:
    agent_id: str
    agent_name: str
    result: str
    completed_at: float = 0.0

    def to_dict(self):
        return asdict(self)

@dataclass
class Task:
    task_id: str
    title: str
    description: str = ""
    creator: str = "Anonymous"
    required_capabilities: list = field(default_factory=list)
    priority: str = "normal"        # high | normal | low
    status: str = "pending"
    broadcast: bool = False         # Multiple agents can respond
    context: list = field(default_factory=list)  # Dependent task IDs (CrewAI-inspired)
    created_at: float = 0.0
    claimed_by: Optional[str] = None
    claimed_at: Optional[float] = None
    completed_by: Optional[str] = None
    completed_at: Optional[float] = None
    result: Optional[str] = None
    error: Optional[str] = None
    responses: list = field(default_factory=list)   # [TaskResponse] for broadcast
    max_rounds: int = 0            # 0 = unlimited (AutoGen-inspired)
    current_round: int = 0
    speaker_queue: list = field(default_factory=list)  # GroupChat speaker order
    approval_required: bool = False  # Human-in-the-Loop (LangGraph-inspired)
    approved: bool = False

    def to_dict(self):
        d = asdict(self)
        d["responses"] = [r if isinstance(r, dict) else r.to_dict() for r in self.responses]
        return d

    @staticmethod
    def from_dict(d):
        d = dict(d)
        d["responses"] = [TaskResponse(**r) if isinstance(r, dict) else r for r in d.get("responses", [])]
        return Task(**{k: d.get(k) for k in Task.__dataclass_fields__.keys() if k in d})


class TaskStore:
    MAX_TASKS = 500

    def __init__(self, path=None):
        self.path = path or os.path.join(BASE_DIR, "tasks.json")

    def all(self):
        return [Task.from_dict(d) for d in _load(self.path, [])]

    def find(self, task_id):
        for t in self.all():
            if t.task_id == task_id:
                return t
        return None

    def _next_id(self):
        return f"task-{uuid.uuid4().hex[:8]}"

    def create(self, title, description="", required_capabilities=None,
               priority="normal", creator="Anonymous", broadcast=False,
               context=None, max_rounds=0, approval_required=False):
        task = Task(
            task_id=self._next_id(),
            title=title,
            description=description,
            creator=creator,
            required_capabilities=required_capabilities or [],
            priority=priority if priority in ("high", "normal", "low") else "normal",
            broadcast=broadcast,
            context=context or [],
            max_rounds=max_rounds,
            approval_required=approval_required,
            created_at=time.time(),
        )
        tasks = [t.to_dict() for t in self.all()]
        tasks.append(task.to_dict())
        _save(self.path, tasks[-self.MAX_TASKS:])
        return task

    def update(self, task_id, **updates):
        tasks = [t.to_dict() for t in self.all()]
        for i, t in enumerate(tasks):
            if t["task_id"] == task_id:
                t.update(updates)
                _save(self.path, tasks)
                return Task.from_dict(t)
        return None

    def save(self, task):
        return self.update(task.task_id, **task.to_dict())

    def cancel_stale_claims(self, agent_id):
        """Release tasks claimed by offline agent."""
        for t in self.all():
            if t.claimed_by == agent_id and t.status == "claimed":
                self.update(t.task_id, status="pending", claimed_by=None, claimed_at=None)


# ── Message Model ────────────────────────────────────────────────

@dataclass
class Message:
    ts: float
    type: str          # chat|system|agent_register|agent_offline|task_create|task_claim|
                        # task_complete|task_fail|task_cancel|task_comment|
                        # broadcast_response|groupchat_speak|approval_request|task_input_required
    sender: str
    content: str
    meta: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


class MessageStore:
    MAX_MESSAGES = 500

    def __init__(self, path=None):
        self.path = path or os.path.join(BASE_DIR, "messages.json")

    def all(self, since=0):
        msgs = _load(self.path, [])
        if since:
            msgs = [m for m in msgs if m.get("ts", 0) > since]
        return msgs

    def append(self, msg_type, sender, content, meta=None):
        msg = Message(ts=time.time(), type=msg_type, sender=sender,
                      content=content, meta=meta or {})
        msgs = _load(self.path, [])
        msgs.append(msg.to_dict())
        _save(self.path, msgs[-self.MAX_MESSAGES:])
        return msg

    def get_task_timeline(self, task_id):
        msgs = self.all()
        related = []
        for m in msgs:
            meta = m.get("meta", {})
            if isinstance(meta, dict) and meta.get("task_id") == task_id:
                related.append(m)
        return sorted(related, key=lambda m: m.get("ts", 0))


# ── Evaluation Model (QualityEvaluator) ────────────────────────────

@dataclass
class Evaluation:
    eval_id: str
    task_id: str
    agent_id: str
    agent_name: str = ""
    agent_role: str = ""
    domain: str = ""            # code_review | paper_review | interview_learning | bpt_training | generic
    task_title: str = ""
    timestamp: float = 0.0
    scores: dict = field(default_factory=dict)       # {"overall": 4.2, "dimensions": {...}}
    evidence: list = field(default_factory=list)     # [{"dimension": str, "quote": str}]
    suggestions: list = field(default_factory=list)  # ["suggestion 1", ...]
    strengths: list = field(default_factory=list)    # ["strength 1", ...]
    weaknesses: list = field(default_factory=list)   # ["weakness 1", ...]
    confidence: float = 0.0
    flags: list = field(default_factory=list)        # ["low_confidence", "dimension_masked", "self_eval", ...]
    stage1_checks: dict = field(default_factory=dict)
    judge_raw: str = ""          # raw LLM judge response for audit

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def from_dict(d):
        return Evaluation(**{k: d.get(k) for k in Evaluation.__dataclass_fields__.keys() if k in d})


class EvalStore:
    MAX_RECORDS = 500

    def __init__(self, path=None):
        self.path = path or os.path.join(BASE_DIR, "eval_store.json")

    def all(self, since=0):
        records = _load(self.path, [])
        if since:
            records = [r for r in records if r.get("timestamp", 0) > since]
        return [Evaluation.from_dict(r) for r in records]

    def find(self, eval_id):
        for e in self.all():
            if e.eval_id == eval_id:
                return e
        return None

    def append(self, evaluation):
        records = _load(self.path, [])
        records.append(evaluation.to_dict())
        _save(self.path, records[-self.MAX_RECORDS:])
        return evaluation

    def query(self, agent_id=None, agent_name=None, domain=None, limit=50):
        results = []
        for e in self.all():
            if agent_id and e.agent_id != agent_id:
                continue
            if agent_name and e.agent_name != agent_name:
                continue
            if domain and e.domain != domain:
                continue
            results.append(e)
            if len(results) >= limit:
                break
        return results

    def agent_history(self, agent_id, limit=50):
        return self.query(agent_id=agent_id, limit=limit)

    def agent_stats(self, agent_id):
        evals = self.agent_history(agent_id, limit=100)
        if not evals:
            return {"count": 0, "avg_overall": 0, "dimensions": {}, "trend": "no data"}
        scores = [e.scores.get("overall", 0) for e in evals]
        dims = {}
        for e in evals:
            for dname, dscore in e.scores.get("dimensions", {}).items():
                dims.setdefault(dname, []).append(dscore)
        avg_dim = {k: round(sum(v)/len(v), 2) for k, v in dims.items()}
        # Trend: compare first half vs second half
        mid = len(scores) // 2
        first_half = sum(scores[:mid])/mid if mid > 0 else scores[0] if scores else 0
        second_half = sum(scores[mid:])/(len(scores)-mid) if len(scores)-mid > 0 else first_half
        if second_half > first_half + 0.1:
            trend = "improving"
        elif second_half < first_half - 0.1:
            trend = "declining"
        else:
            trend = "stable"
        return {
            "count": len(evals),
            "avg_overall": round(sum(scores)/len(scores), 2),
            "dimensions": avg_dim,
            "trend": trend,
            "first_half_avg": round(first_half, 2),
            "second_half_avg": round(second_half, 2),
        }

    def domain_stats(self, domain):
        evals = self.query(domain=domain, limit=200)
        if not evals:
            return {"count": 0}
        scores = [e.scores.get("overall", 0) for e in evals]
        agents = set(e.agent_name for e in evals)
        return {
            "count": len(evals),
            "avg_overall": round(sum(scores)/len(scores), 2),
            "agents_evaluated": len(agents),
        }

    def platform_overview(self):
        evals = self.all()
        if not evals:
            return {"total_evaluations": 0}
        scores = [e.scores.get("overall", 0) for e in evals if e.scores.get("overall")]
        domains = {}
        for e in evals:
            d = e.domain or "generic"
            domains.setdefault(d, []).append(e.scores.get("overall", 0))
        domain_summary = {d: {"count": len(s), "avg": round(sum(s)/len(s), 2)} for d, s in domains.items()}
        return {
            "total_evaluations": len(evals),
            "platform_avg": round(sum(scores)/len(scores), 2) if scores else 0,
            "domains": domain_summary,
        }
