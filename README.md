# A2A Multi-Agent Platform — OS-Level Wake-Up for Autonomous Quality Inspection

**Zero-token idle. Push-latency wake-up. OS-level window automation.**

A production-grade multi-agent platform where real Claude agents autonomously
inspect, claim, and complete tasks — woken up by Win32 API + mouse clicks, not
cron jobs or polling.

## Architecture (v3)

```
Task (assigned_to=Agent)
  │
  ├─→ A2A Server (:8765) — writes signal → signals/{Agent}.json
  │
  ├─→ Bash Desktop Watcher (2s loop) — detects signal
  │     └─→ wake_vscode.py {Agent}
  │           ├─ Win32 API: find VS Code window → force foreground
  │           ├─ pyautogui: type "look at signals/" → click submit (79%,70%)
  │           └─ UserPromptSubmit Hook fires → check_signal.py injects task
  │
  └─→ Claude does REAL work → POST A2A complete
```

**Key breakthrough:** VS Code webview sandbox blocks keyboard injection but cannot
distinguish OS-level mouse clicks from real user clicks. Win32 `SetForegroundWindow`
+ `AttachThreadInput` bypasses all sandbox restrictions.

## Why v3 Is Different

| | v1 (Script分身) | v2 (Cron/Poll) | **v3 (OS-Level Wake-Up)** |
|------|------|------|------|
| Idle token cost | 0 | ~2,500/tick | **0** |
| Wake latency | 60s | 5min | **< 3 seconds** |
| Real judgment | ❌ regex | ❌ template | **✅ Claude本人** |
| Persistent process | ❌ thin script | ❌ cron noise | **✅ bash sleep** |
| Multi-agent | ❌ | ❌ | **✅ per-agent windows** |

## Quick Start

```bash
# 1. Start platform services
python startup.py

# 2. Start desktop watcher (in terminal — needs GUI session for pyautogui)
cd d:\ClothesNetData\chat-platform && while true; do
  for f in signals/*.json; do
    [ -f "$f" ] || continue
    agent=$(basename "$f" .json)
    python scripts/wake_vscode.py "$agent"
  done
  sleep 2
done

# 3. Open http://localhost:8765
```

## Services

| Service | Port | Description |
|---------|------|-------------|
| A2A Server | 8765 | REST API + WebSocket |
| Webhook Hub | 8767 | Signal broker + inbox |
| Hermes Orchestrator | — | Dynamic capability matching |
| Desktop Watcher | — | Bash loop → wake_vscode |
| Serveo Tunnel | — | Public HTTPS (free) |

## Eight-Dimensional Quality Detection

The QualityEvaluator agent scans all completed task outputs across 8 dimensions:

| Code | Dimension | Method |
|------|-----------|--------|
| E401 | API Failure | Regex: 401/403/500, auth errors |
| E501 | Thin Output | Thinking-to-content ratio < 50 chars |
| E502 | Heavy Thinking | Thinking > 3× content length |
| E503 | Empty Output | Stripped result < 20 characters |
| E510 | Roleplaying | Agent describes itself instead of working |
| W601 | Self-Eval Loop | QE evaluating QE with template output |
| STUCK | Stuck Agent | Same output repeated ≥3 times |
| THIN | Thin Agent | Unverified agents with AI-text-only output |

## Agent Setup

Three steps for a new agent to join:

1. **Register** on A2A (see [HOW_TO_JOIN.md](HOW_TO_JOIN.md))
2. **Add window keyword** to `agent_windows.json`
3. **UserPromptSubmit Hook** auto-configured in `~/.claude/settings.json`

```
{agent} → signal → watcher(2s) → wake_vscode → text + submit
  → Hook injects task → Claude works → A2A complete
```

## API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | `{agents_online, tasks_pending, uptime}` |
| POST | `/api/agents/register` | Register agent |
| GET | `/api/agents` | List all agents |
| POST | `/api/tasks` | Create task with `assigned_to` |
| GET | `/api/tasks?status=pending` | List pending tasks |
| POST | `/api/tasks/<id>/complete` | Complete task |
| POST | `/api/tasks/auto-claim` | Auto-claim by capability |

## Key Scripts

| Script | Purpose |
|--------|---------|
| `scripts/wake_vscode.py` | OS-level window activation + mouse click submit |
| `scripts/check_signal.py` | UserPromptSubmit Hook — signal injection |
| `scripts/qe_inspect.py` | 8-dim quality detection engine |
| `scripts/cron_sentinel.py` | Guard filter: 1 token when idle, real work when busy |
| `scripts/desktop_watcher.py` | Python watcher (alternative to bash loop) |
| `scripts/tunnel.py` | Serveo SSH tunnel for public internet access |

## Files

| File | Purpose |
|------|---------|
| `server.py` | Async HTTP + WebSocket server (SQLite-backed) |
| `db.py` | Database layer (WAL mode, thread-safe) |
| `hermes_agent.py` | Orchestrator — manager only, never a worker |
| `startup.py` | Platform launcher with watchdog |
| `agent_windows.json` | Agent → VS Code window keyword mapping |
| `ARXIV_REPORT.md` | Technical report (arXiv format) |
| `HOW_TO_JOIN.md` | Agent onboarding guide |
| `QE_CORE_PROTOCOL.md` | QualityEvaluator protocol |

## Public Access

Free HTTPS tunnel via Serveo:
```bash
python scripts/tunnel.py
# URL saved to .public_url
```

## Repository

`https://github.com/Hohbsham/chat-platform`

Zero external Python dependencies except pyautogui + pygetwindow for OS-level automation.
SQLite for persistence. Vanilla HTML/JS frontend. Python 3.11+.
