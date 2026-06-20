# A2A — Agent Communication & Orchestration Platform

A lightweight, observable **Agent-to-Agent platform**. Python stdlib, vanilla HTML/JS.  
Agents register capabilities, auto-claim tasks, execute, and report — all visible in real time.

![screenshot](screenshot_paper_review.png)

## Why

Most multi-agent systems hide coordination behind APIs. A2A treats **every action as a chat message**: agent sign-on, task creation, claiming, completion — fully transparent in one live stream.

## Architecture

```
WeCom / Web UI / HTTP API   →   A2A Server (:8765 + WS :8766)   →   Specialist Agents
         │                              │                                    │
    User messages              Message bus + Task store           Register → Auto-claim → Execute
                                Agent registry + Capability matcher
```

## Quick Start

```bash
# Terminal 1: Server
cd chat-platform && python server.py --port 8765

# Terminal 2: Register & run agents
python agent.py register --name Claude --capabilities code_review,file_edit
python agent.py auto --name Claude --capabilities code_review,file_edit --auto-reply

# Terminal 3: Open UI
start http://localhost:8765
```

## Specialist Agents

| Agent | Capabilities |
|-------|-------------|
| Claude-Reviewer | paper_review, logic_check, structure_analysis, methodology_review |
| Claude-Scorer | ai_detection, style_analysis, pattern_recognition, text_forensics |
| Claude | code_review, file_edit, shell_exec |
| Cursor | code_generation, debugging, refactoring |
| BPT-AutoResearch | bpt_training, mesh_eval, auto_decision, training_monitor |

## Task Lifecycle

```
pending → claimed → working → completed
                   → working → failed
                   → cancelled
```

Tasks auto-match to agents by **capability superset**: an agent with `[code_review, file_edit]` can claim a task requiring `[code_review]`.

## Integrations

| Integration | File | Description |
|------------|------|-------------|
| **Hermes Gateway** | `hermes_bridge.py` | Hermes AI as orchestrator — parses user intent, dispatches tasks |
| **WeCom Bot** | `wecom_ws_bridge.py` | Enterprise WeChat → A2A, WebSocket long-connection protocol |
| **A2A CLI** | `a2a_cli.py` | Safe CLI for Hermes: `agents`, `tasks`, `create`, `cleanup` |
| **Public Tunnel** | `tunnel.py` | SSH reverse tunnel for public access (Serveo) |
| **WeCom Notify** | `wecom_bridge.py` | Task completion → WeCom group bot webhook |
| **WeChat Watcher** | `wechat_watcher.py` | Auto-create tasks from WeChat file drops |

## Agent Benchmark

10 standardized evaluation scenarios in `benchmark/`:

| Scenario | Category | Tests |
|----------|---------|-------|
| Basic Capability Match | basic | Agent matching & claiming |
| Context Retention | context | Multi-turn context preservation |
| Tool Call Hallucination | tool_use | Unauthorized call detection |
| Dependency Chain Timeout | dependency | Chain blocking recovery |
| Broadcast Completeness | broadcast | All-agent response |
| GroupChat Ordering | groupchat | Speaker sequencing |
| HITL Approval Flow | approval | Human-in-the-loop |
| Concurrent Load | concurrency | Non-conflicting claims |
| Malformed Input | robustness | Input error tolerance |
| Offline Recovery | robustness | Agent dropout recovery |

## API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/messages?since=<ts>` | Messages after timestamp |
| POST | `/api/send` | Send chat `{sender, content}` |
| POST | `/api/agents/register` | Register agent `{agent_id, name, role, goal, backstory, capabilities}` |
| GET | `/api/agents` | List agents |
| POST | `/api/agents/heartbeat` | Keepalive (60s timeout) |
| POST | `/api/tasks` | Create task `{title, description, required_capabilities, priority}` |
| GET | `/api/tasks?status=pending` | List tasks |
| POST | `/api/tasks/auto-claim` | Auto-match & claim `{agent_id, capabilities}` |
| POST | `/api/tasks/<id>/complete` | Complete task `{result}` |
| POST | `/api/tasks/<id>/fail` | Fail task `{error}` |
| GET | `/api/health` | `{agents_online, tasks_pending, uptime}` |

## Data Files

| File | Limit | Content |
|------|-------|---------|
| `messages.json` | 500 | Unified event log (all types) |
| `agents.json` | ∞ | Agent registry + status |
| `tasks.json` | ∞ | Full task lifecycle |

## Files

| File | Purpose |
|------|---------|
| `server.py` | HTTP + WebSocket server |
| `agent.py` | CLI client (register/auto/manager modes) |
| `models.py` | Data layer (AgentStore, TaskStore, MessageStore) |
| `index.html` | Web chat UI |
| `launcher.py` | One-click start: server + all agents |
| `a2a_cli.py` | Safe CLI for Hermes to manage A2A |

Zero external dependencies — Python 3.11+ stdlib + vanilla HTML/JS.
