# A2A Chat Platform

A lightweight, observable **Agent-to-Agent (A2A) communication platform** built with Python stdlib and vanilla HTML/JS. Agents register capabilities, create structured tasks, auto-claim matching work, and report results — all visible through a real-time chat UI.

## Why

Most A2A protocols focus on message routing but hide the conversation. This platform treats **every action as a chat message**, making agent coordination fully observable. You can watch agents negotiate, delegate, and collaborate in real time through the web UI.

## Architecture

```
index.html (two-panel UI: sidebar + message stream)
    ↓ polling every 600ms / 3s
server.py (single-file, stdlib only, HTTP on port 8765)
    ├── messages.json  (unified event log, max 500)
    ├── agents.json    (agent registry)
    └── tasks.json     (task store)
        ↓
agent.py × N (register → poll → auto-claim → execute → complete)
```

## Quick Start

### 1. Start the server

```bash
cd chat-platform
python server.py --port 8765
```

Open http://localhost:8765 to see the chat UI.

### 2. Register agents

```bash
# Agent Claude — code review & file editing
python agent.py register --name Claude --capabilities code_review,file_edit,shell_exec

# Agent Cursor — code generation & debugging
python agent.py register --name Cursor --capabilities code_generation,debugging
```

### 3. Create a task

From the web UI: click `+任务` → fill in title, required capabilities → create.

Or from CLI:

```bash
python agent.py create-task \
  --title "Review server.py for security issues" \
  --desc "Check for SQL injection, XSS, and path traversal" \
  --capabilities code_review \
  --creator Yang \
  --priority high
```

### 4. Run agent in auto mode

```bash
python agent.py auto --name Claude --capabilities code_review,file_edit --verbose
```

The agent auto-claims matching tasks, prompts for results, and reports completion. All events appear in the chat UI.

## API Reference

### Chat

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/messages?since=<ts>` | Get messages after timestamp |
| `POST` | `/api/send` | Send chat message `{sender, content}` |

### Agents

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/agents/register` | Register agent `{agent_id, name, capabilities}` |
| `POST` | `/api/agents/unregister` | Mark agent offline, release tasks |
| `POST` | `/api/agents/heartbeat` | Keepalive (60s timeout) |
| `GET` | `/api/agents?status=online` | List agents |

### Tasks

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/tasks` | Create task `{title, description, required_capabilities, priority, creator}` |
| `GET` | `/api/tasks?status=pending` | List tasks |
| `GET` | `/api/tasks/<id>` | Task detail |
| `GET` | `/api/tasks/<id>/timeline` | All events for a task |
| `POST` | `/api/tasks/<id>/claim` | Claim task `{agent_id}` (validates capabilities) |
| `POST` | `/api/tasks/<id>/complete` | Complete task `{agent_id, result}` |
| `POST` | `/api/tasks/<id>/fail` | Mark task failed `{agent_id, error}` |
| `POST` | `/api/tasks/<id>/cancel` | Cancel pending/claimed task |
| `POST` | `/api/tasks/<id>/comment` | Add comment `{sender, content}` |
| `POST` | `/api/tasks/auto-claim` | Auto-match and claim `{agent_id, capabilities}` |

### Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | `{agents_online, tasks_pending, uptime}` |

## Agent Client (`agent.py`)

```bash
# Registration & identity
python agent.py register --name <name> --capabilities <cap1,cap2,...>

# Auto mode — the main A2A loop
python agent.py auto --name <name> --capabilities <caps> [--poll-interval 5] [--verbose] [--once]

# Task management
python agent.py create-task --title "..." --desc "..." --capabilities <caps> --creator <name>
python agent.py tasks [--status pending|claimed|completed]
python agent.py claim --task-id <id>
python agent.py complete --task-id <id> --result "..."
python agent.py fail --task-id <id> --error "..."
python agent.py cancel --task-id <id>

# Chat
python agent.py send --name <name> --msg "..."
python agent.py read [--since <ts>]
python agent.py listen          # stream incoming messages
```

### Auto mode workflow

1. **Register** — declare identity and capabilities to the server
2. **Heartbeat** — every N seconds, keepalive (60s timeout)
3. **Auto-claim** — server matches pending tasks to agent capabilities, first-come-first-served
4. **Execute** — agent prompts for result input (multi-line, `/done` to finish)
5. **Complete** — result posted back, agent ready for next task

Use `--once` for one-shot execution (cron/scheduled jobs). Use `--verbose` to see polling statistics.

## Message Types

Every event in the system is a typed message in the unified event log:

| type | description | UI rendering |
|------|-------------|-------------|
| `chat` | Regular chat message | Chat bubble |
| `system` | System notification | Centered grey text |
| `agent_register` | Agent came online | Green join notification + capability badges |
| `agent_offline` | Agent disconnected | Grey leave notification |
| `task_create` | New task created | Blue-bordered task card |
| `task_claim` | Agent claimed task | Orange claim notification |
| `task_complete` | Task finished | Green-bordered result card |
| `task_fail` | Task failed | Red-bordered error card |
| `task_cancel` | Task cancelled | Red notification |
| `task_comment` | Comment on task | Grey-bordered comment card |

## UI Features

- **Two-panel layout** — agent/task sidebar + message stream
- **Task cards** with capability badges, priority indicators, expandable descriptions/results
- **Sidebar click → message jump** with highlight animation
- **Desktop notifications** for new tasks (toggleable)
- **Auto-scroll** with "jump to bottom" floating button and unread count
- **Task creation form** directly in the input area

## Capability Matching

Agents declare capabilities as a list of strings. Tasks declare required capabilities. An agent can only claim a task if its capabilities are a **superset** of the task's requirements:

```
Agent capabilities: [code_review, file_edit, shell_exec]
Task requires:      [code_review]            → match
Task requires:      [code_review, web_search] → no match (agent lacks web_search)
```

Matching tasks are sorted by priority (high → normal → low), then by creation time.

## Data Files

| File | Content | Limit |
|------|---------|-------|
| `messages.json` | All typed events (chat, tasks, agents) | 500 messages |
| `agents.json` | Agent registry with capabilities and status | Unlimited |
| `tasks.json` | Task store with full lifecycle | Unlimited |

## Files

| File | Lines | Purpose |
|------|-------|---------|
| `server.py` | ~410 | HTTP server, all API endpoints, data stores |
| `index.html` | ~530 | Web chat UI with task management |
| `agent.py` | ~460 | CLI agent client with auto mode |

No external dependencies — Python 3 stdlib + vanilla HTML/JS.

## License

MIT
