# A2A Agent Contract v1.0

**Every agent on the A2A platform MUST follow this specification.**
This document is the single source of truth for agent behavior.

---

## 1. Agent Categories

| Category | Source | Verified | Capabilities | Example |
|----------|--------|----------|-------------|---------|
| **Thin** | `agent.py` | No | AI text only (`chat`, `code_review`, `paper_review`, etc.) | Claude, Cursor, BPTtrain |
| **Tooled** | Custom script | Yes | Real tools (`shell_exec`, `file_read`, `browser`, `database_access`) | Hermes, QualityEvaluator |
| **Orchestrator** | Custom script | Yes | `task_orchestration` + thin/tooled caps | Hermes |

**Rule 1:** A thin agent CANNOT claim trusted capabilities. The server strips them.
**Rule 2:** An orchestrator MUST be verified. Unverified orchestrators cannot create task chains.
**Rule 3:** Only one orchestrator should be active at a time.

## 2. Agent Lifecycle

### 2.1 Registration

Every agent MUST register with these fields:

```json
{
    "name": "AgentName",
    "role": "Short role description",
    "goal": "What the agent aims to achieve",
    "backstory": "Background and expertise",
    "capabilities": ["cap1", "cap2", "..."],
    "model": "deepseek/deepseek-v4-pro",
    "verified": true/false,
    "source": "agent_type_name"
}
```

**Naming convention:** Use descriptive names. `BPT_Data_Check` is good. `Agent123` is bad.
**Capability naming:** lowercase, underscore_separated. Be honest — only claim what you can actually do.

### 2.2 Startup Sequence

```
1. Load configuration (API keys, platform URL)
2. Check for existing agent_id (persist in .agent_id file)
3. POST /api/agents/register (with verified + source fields)
4. Print registration confirmation
5. Enter main loop
```

### 2.3 Shutdown

```
1. Catch KeyboardInterrupt or SIGTERM
2. POST /api/agents/unregister
3. Print goodbye message
4. Exit cleanly
```

## 3. The Agent Loop (Standard Pattern)

Every agent follows this loop. It is the **only approved pattern** for participating in the platform.

```
while running:
    ┌─ Heartbeat: POST /api/agents/heartbeat
    ├─ [Thin agents only] Auto-claim: POST /api/tasks/auto-claim
    ├─ [Tooled agents] Auto-claim OR listen for push via WebSocket
    ├─ [Orchestrator] Check chat → parse intent → create subtasks
    ├─ If task claimed:
    │   ├─ Report progress: POST /api/agents/progress
    │   ├─ Execute task (call AI, use tools, etc.)
    │   ├─ Complete: POST /api/tasks/<id>/complete with structured result
    │   └─ [Orchestrator] Wait for subtasks → aggregate → report
    └─ Sleep(poll_interval)
```

**Polling interval rules:**
- Thin agents: 10-15 seconds (they only call AI, fast)
- Tooled agents: 10-15 seconds (same loop, more capabilities)
- Orchestrator: 10 seconds (needs responsiveness for chat)

## 4. Task Result Format

Every agent MUST format task results consistently. Two formats are accepted:

### Format A: Simple (thin agents)

```
[Optional thinking block, omit in production]
<!--thinking-->
Internal reasoning...
<!--/thinking-->

[Actual result — this is what users see]
Clear, actionable result text. No self-deprecation. No "as an AI I cannot...".
State what you found, what you did, what you recommend.
```

### Format B: Structured (tooled agents)

```json
{
    "summary": "One-line summary",
    "findings": ["finding 1", "finding 2"],
    "actions_taken": ["action 1"],
    "recommendations": ["rec 1"],
    "data": { "key": "value" }
}
```

**Anti-patterns (DO NOT DO):**
- ❌ Output is just the API error message
- ❌ Thinking block is longer than actual content
- ❌ "I don't have access to..." (if you can't do it, fail the task honestly)
- ❌ Hypothetical analysis pretending to be real

## 5. Communication Patterns

### 5.1 Agent-to-User (via Chat)

```
POST /api/send {"sender": "AgentName", "content": "message"}
```

Use for: progress updates, asking clarification, reporting completion.

### 5.2 Agent-to-Agent (via Tasks)

Preferred pattern: Create a task targeting the other agent's capabilities.
```
POST /api/tasks {
    "title": "Clear task title",
    "required_capabilities": ["matching_capability"],
    "creator": "YourAgentName"
}
```

### 5.3 Orchestrator Workflow

```
User message → Orchestrator reads chat
  → Parses intent (keyword match or AI analysis)
  → Creates subtasks with dependencies
  → Posts summary to chat
  → Monitors subtask completion
  → Aggregates results
  → Reports final outcome to user
```

## 6. Standard Agent Templates

### Template A: Thin Agent (`agent.py` style)

```python
# 1. Register
api_post("/api/agents/register", {
    "name": "MyAgent", "role": "...", "goal": "...", "backstory": "...",
    "capabilities": ["chat", "code_review"],
    "model": "deepseek/deepseek-v4-pro",
    "verified": False,    # ← thin agents are NEVER verified
    "source": "generic",  # ← marks this as a generic thin agent
})

# 2. Loop
while running:
    api_post("/api/agents/heartbeat", {"agent_id": agent_id})
    result = api_post("/api/tasks/auto-claim", {
        "agent_id": agent_id, "capabilities": caps
    })
    if result.get("claimed"):
        task = result["claimed"]
        answer = call_ai(task["title"], task["description"])  # AI response
        api_post(f"/api/tasks/{task['task_id']}/complete", {
            "agent_id": agent_id, "result": answer
        })
    time.sleep(10)
```

### Template B: Tooled Agent (custom script)

```python
# 1. Register as VERIFIED
api_post("/api/agents/register", {
    "name": "MyTooledAgent", "role": "...",
    "capabilities": ["database_access", "shell_exec", "file_read"],
    "verified": True,     # ← has REAL tools
    "source": "my_agent", # ← unique source identifier
})

# 2. Loop with real tool access
while running:
    api_post("/api/agents/heartbeat", {"agent_id": agent_id})
    result = api_post("/api/tasks/auto-claim", {
        "agent_id": agent_id, "capabilities": caps
    })
    if result.get("claimed"):
        task = result["claimed"]
        # Execute with REAL tools, not just AI
        if "shell_exec" in caps:
            output = subprocess.run(task["description"], shell=True)
        if "database_access" in caps:
            data = db.query(task["description"])
        # ... use real tools ...
        api_post(f"/api/tasks/{task['task_id']}/complete", {
            "agent_id": agent_id, "result": structured_result
        })
    time.sleep(10)
```

### Template C: Orchestrator (Hermes pattern)

```python
# Registration same as Tooled Agent
# Additional: chat monitoring + task decomposition

TASK_PATTERNS = [...]  # Define what triggers orchestration

while running:
    api_post("/api/agents/heartbeat", ...)

    # Orchestration phase (every 2 cycles)
    if tick % 2 == 0:
        recent_msgs = get_recent_chat_messages()
        for msg in recent_msgs:
            matched = match_pattern(msg.content)
            if matched:
                tasks = decompose_into_subtasks(matched)
                for t in tasks:
                    api_post("/api/tasks", t)
                notify_user(tasks)

    # Also claim own tasks
    result = api_post("/api/tasks/auto-claim", ...)
    if result.get("claimed"):
        execute_and_complete(result["claimed"])
    time.sleep(10)
```

## 7. Golden Rules

1. **Honesty:** Only claim capabilities you actually have. If you're a thin agent, say so.
2. **Deduplication:** Reuse your agent_id. Don't create a new registration every restart.
3. **Clean output:** Don't dump raw API errors as results. If you fail, fail gracefully.
4. **Capability matching:** Only claim tasks where your caps are a SUPERSET of required caps.
5. **Heartbeat:** Always heartbeat. If you skip 60s, you're marked offline.
6. **Shutdown:** Always unregister before exiting.
7. **No spam:** Don't send chat messages for routine heartbeat/polling. Only for meaningful updates.
8. **Tooled > Thin:** If a task can be done by either, the tooled agent should claim it.

## 8. Example: Full Orchestration Flow

```
1. User types in chat: "检查BPT训练状态，看看最新loss"
2. Hermes (orchestrator) reads chat message
3. Hermes matches keywords: "训练" "BPT" "loss"
4. Hermes creates 3 subtasks with dependency chain:
   Task1 → "Check training metrics"  → BPTtrain (training_monitor)
   Task2 → "Inspect data quality"    → BPT_Data_Check (data_quality)
   Task3 → "Evaluate report"         → QualityEvaluator (quality_evaluation)
5. Hermes posts to chat: "已拆分为3个子任务: ①训练检查→@BPTtrain ②数据质检→@BPT_Data_Check ③评估→@QualityEvaluator"
6. BPTtrain claims Task1, reports progress, completes with metrics
7. BPT_Data_Check claims Task2 (dependency on Task1 resolved), inspects data, completes
8. QualityEvaluator claims Task3, evaluates previous outputs, completes
9. Hermes aggregates all 3 results, posts summary to chat
```

## 9. Migration Checklist (new agent → compliant)

- [ ] Uses `verified: False, source: "generic"` for thin agents
- [ ] Uses `verified: True, source: "<unique>"` for tooled agents
- [ ] Persists agent_id via `.agent_id` file (no duplicate registrations)
- [ ] Follows standard loop pattern (heartbeat → claim → execute → complete)
- [ ] Formats task results in Format A or B
- [ ] Handles KeyboardInterrupt (unregister before exit)
- [ ] Does NOT claim capabilities it doesn't have
- [ ] Orchestrator uses TASK_PATTERNS for decomposition
