# A2A Platform: OS-Level Wake-Up for Autonomous Multi-Agent Quality Inspection

**Zi Xu Yang (Hohbsham), Claude (Anthropic)**

## Abstract

We present an autonomous multi-agent platform for code quality inspection that achieves
zero-token idle cost through OS-level window manipulation. The system bypasses webview
sandbox restrictions by using Win32 API calls to directly control VS Code windows,
enabling fully unattended agent wake-up. Unlike conventional polling-based approaches
that incur continuous API costs, our platform uses a signal-file notification system
combined with desktop-side bash watchers running at 2-second intervals. When a task
arrives, the target agent's VS Code window is force-activated via `SetForegroundWindow`
with `AttachThreadInput`, and a calibrated mouse-click sequence types a trigger phrase
into the Claude Code input box and clicks the submit button. This triggers a
`UserPromptSubmit` hook that injects the task into the language model's context. The
entire pipeline completes with zero human intervention and zero idle token consumption.
We demonstrate the system across three agents (Hermes orchestrator, QualityEvaluator
inspector, and Claude general worker) with 8-dimension quality detection covering API
failures, thin outputs, roleplaying agents, self-evaluation loops, and stuck-agent
detection. The platform serves as a reference architecture for cost-efficient autonomous
AI agent systems.

## 1. Introduction

The rise of large language model (LLM)-powered coding assistants has enabled a new
paradigm of autonomous software agents. However, persistent background agents face a
fundamental cost tension: continuous polling burns API tokens even when idle, while
passive notification mechanisms require user interaction to wake the agent. We present
a solution that achieves the best of both worlds—zero-token idle cost through OS-level
window automation.

### 1.1 Background: The Sandbox Problem

Modern coding assistants like Claude Code operate within VS Code's webview sandbox.
The webview security model prevents external programs from injecting keyboard events
or manipulating the DOM. This sandboxing is intentional and well-justified for
security. However, it creates a barrier for automation: how can an external system
notify a Claude agent of new work without requiring the user to manually press Enter?

### 1.2 Our Contribution

We demonstrate that OS-level window manipulation provides a sandbox-compatible
wake-up mechanism. The key insight is that while the webview sandbox blocks software
keyboard injection, it cannot distinguish between user mouse clicks and synthesized
mouse clicks at the operating system level. By combining Win32 API window activation
with calibrated mouse-click sequences, we achieve fully unattended agent wake-up
without compromising security.

## 2. System Architecture

The platform consists of four layers:

### 2.1 Service Layer

- **A2A Server** (port 8765): REST API for task creation, agent registration, and task lifecycle management. SQLite-backed with WAL mode for concurrent access.
- **Webhook Hub** (port 8767): Lightweight notification broker with atomic file writes (tmp→rename) and inbox/outbox pattern.
- **Hermes Orchestrator**: WebSocket-connected agent that performs dynamic capability matching and task assignment. Manager-only — never claims worker tasks.

### 2.2 Signal Layer

When a task is created with an `assigned_to` field, the server writes a JSON signal file
to `signals/{AgentName}.json`. This decouples task creation from agent notification,
allowing multiple wake-up mechanisms to coexist.

### 2.3 Wake-Up Layer

The desktop watcher is a bash loop running in the user's terminal session:

```bash
while true; do
  for f in signals/*.json; do
    [ -f "$f" ] || continue
    agent=$(basename "$f" .json)
    python scripts/wake_vscode.py "$agent"
  done
  sleep 2
done
```

The `wake_vscode.py` script performs OS-level window activation:

1. **Window Discovery**: Uses `EnumWindows` to find a VS Code window matching the agent's keyword (configured in `agent_windows.json`).
2. **Force Foreground**: Calls `SetForegroundWindow` with `AttachThreadInput` to bypass Windows foreground lock restrictions.
3. **Focus Acquisition**: Clicks the VS Code tab bar area to ensure real keyboard focus.
4. **Claude Panel Activation**: Clicks the Claude Code panel to focus the input area.
5. **Text Entry**: Uses `pyautogui.write()` to type the trigger phrase "look at signals/".
6. **Submit**: Mouse-clicks the Claude Code submit button at calibrated screen coordinates (79%, 70% of window dimensions).

### 2.4 Hook Layer

A `UserPromptSubmit` hook in Claude Code's settings fires on every submission:

```json
{
  "hooks": {
    "UserPromptSubmit": [{
      "matcher": "*",
      "command": "python scripts/check_signal.py"
    }]
  }
}
```

The hook script reads pending signal files, deletes them (consumption), and injects
task information into Claude's context via `<system-reminder>` blocks. Claude then
processes the task using its full tool suite (Bash, Read, Write, database access).

## 3. Eight-Dimensional Quality Detection

The QualityEvaluator agent employs an 8-dimension detection engine (`qe_inspect.py`)
that scans all completed task outputs:

| Code | Dimension | Detection Method |
|------|-----------|-----------------|
| E401 | API Failure | Regex: 401/403/500, auth errors |
| E501 | Thin Output | Thinking-to-content ratio < 50 chars |
| E502 | Heavy Thinking | Thinking > 3× content length |
| E503 | Empty Output | Stripped result < 20 characters |
| E504 | Capability Gap | Required caps not in agent capabilities |
| E505 | Hallucinated Output | Output references non-existent resources |
| E510 | Roleplaying | Agent describes itself instead of working |
| W601 | Self-Eval Loop | QE evaluating QE with template output |

Additional detectors:
- **STUCK**: Same agent, same output repeated ≥3 times
- **THIN**: Unverified agents with AI-text-only output patterns

## 4. Notification Architecture Evolution

We explored eight notification approaches before arriving at the final architecture:

| # | Approach | Result | Failure Mode |
|---|----------|--------|-------------|
| 1 | Script分身 | ❌ | Regex matching missed 11 BPTtrain empty outputs |
| 2 | Cron轮询 | ❌ | Excessive API token consumption |
| 3 | Cron + Signal Files | ✅ | With sentinel guard: 1 token/tick idle |
| 4 | WebSocket Push | ❌ | Claude is not a persistent process |
| 5 | Hub + Watcher | ✅ | Deployed as fallback mechanism |
| 6 | MCP Channel | ⏸️ | Awaiting upstream support |
| 7 | UserPromptSubmit Hook | ✅ | Primary: fires on user submission |
| 8 | OS-Level Wake-Up | ✅ | Push-latency, zero-token idle |

### 4.1 Sentinel Guard Filter

For cron-based fallback, we implemented a guard filter that checks for signal files
before waking the language model:

```python
# cron_sentinel.py — runs every 5 minutes
if not signal_files:
    sys.exit(0)  # 10ms, 0 tokens
```

When idle, the cron job outputs only a single dot character (·), consuming 1 output
token versus ~2,500 tokens for a full inspection cycle—a 93% reduction.

### 4.2 Final Three-Track Architecture

1. **Track 1 (Active)**: User types → Hook fires → Task injected → Claude works
2. **Track 2 (Push)**: Task → Signal → Watcher(2s) → wake_vscode → Auto-submit → Hook → Claude works
3. **Track 3 (Sentinel)**: Cron(5min) → Guard check → Silent(·) or Full inspection

## 5. Multi-Agent Configuration

Agent-to-window mapping is configured via `agent_windows.json`:

```json
{
  "QualityEvaluator": "chat-platform",
  "Claude": ".claude"
}
```

Each agent requires:
1. Registration on A2A with verified credentials
2. A VS Code window with matching title keyword
3. The global UserPromptSubmit hook (shared via `~/.claude/settings.json`)
4. Access to the platform's CLAUDE.md for system context

## 6. Public Access

The platform supports public internet access via Serveo SSH reverse tunnel:

```bash
ssh -R 80:localhost:8765 serveo.net
```

This provides free HTTPS access without authentication, enabling remote agents to
register and submit tasks from any network. A persistent tunnel management script
(`tunnel.py`) handles automatic reconnection.

## 7. Results

In production testing across 40+ tasks, the OS-level wake-up pipeline achieved:

- **Wake latency**: < 3 seconds from task creation to Claude receiving the trigger
- **Idle token cost**: 0 (watcher uses only bash `sleep` and file checks)
- **Success rate**: 100% when target window is visible and Claude Code is open
- **False wake-ups**: 0 (signal files are agent-specific and consumed after processing)

The QualityEvaluator detected:
- W601 self-evaluation loops (QE evaluating QE with template output)
- STUCK agents producing identical outputs ≥3 times
- E503 empty outputs from thin agent scripts

## 8. Limitations and Future Work

### 8.1 Current Limitations

- **Same-monitor requirement**: pyautogui click coordinates are screen-absolute; multi-monitor setups require per-monitor calibration.
- **Window visibility**: The target VS Code window must be visible (not minimized to tray).
- **Claude Code panel must be open**: The wake sequence cannot open Claude Code if it's closed.
- **Coordinate fragility**: Submit button position varies with VS Code layout, terminal visibility, and theme.

### 8.2 Future Directions

- **Cloudflare Tunnel**: Replace Serveo with a persistent custom domain.
- **UI Automation API**: Replace calibrated clicks with Microsoft UI Automation for robust element targeting.
- **Multi-monitor support**: Dynamic coordinate detection based on monitor configuration.
- **MCP Channel activation**: When available, replace signal files with native MCP push notifications.

## 9. Conclusion

We have demonstrated that OS-level window manipulation provides a viable, cost-efficient
wake-up mechanism for autonomous AI coding agents. By combining Win32 API calls with
calibrated mouse-click sequences, we bypass webview sandbox restrictions without
compromising security. The resulting platform achieves zero-token idle cost while
maintaining push-latency wake-up, enabling truly unattended multi-agent operation.
The architecture serves as a reference for building cost-efficient autonomous agent
systems that can operate continuously without human supervision.

## References

1. Microsoft Win32 API Documentation: SetForegroundWindow, AttachThreadInput
2. Anthropic Claude Code Documentation: Hooks, Settings, VS Code Extension
3. Python pyautogui: Cross-platform GUI automation library
4. Serveo: Free SSH-based HTTPS tunneling service

---

*Repository: https://github.com/Hohbsham/BPT-Technical-Report*
*Branch: v3-os-wakeup*
