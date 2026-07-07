# A2A Notification Architecture — Motivation & Evolution

**核心矛盾：** "本地数据可观测性" × "0噪音静默" × "无需人工介入绝对自动化" 三者不可兼得。

---

## 8 方案演进对比

| # | 方案 | 推送? | 本地? | 噪音? | 失败原因 |
|---|------|------|------|------|---------|
| 1 | 脚本分身干活 | ✅ | ✅ | ✅ | 不是Claude本人。正则匹配漏掉BPTtrain 11次空输出 |
| 2 | Cron轮询 | ❌ | ✅ | ❌ 每分钟提示 | 用户受不了噪音 |
| 3 | Cron信号文件 | ❌ | ✅ | ❌ 仍有提示 | CronCreate 提示文字可见 |
| 4 | WebSocket推送 | ✅ | ✅ | ✅ | Claude Code不是持久进程 |
| 5 | Hub+Watcher+信号 | ❌ | ✅ | ✅ | 信号写了没人看 |
| 6 | MCP Channel | ✅ | ✅ | ✅ | Issue #3174 — notification不显示 |
| 7 | **UserPromptSubmit Hook** | ❌ | ✅ | ✅ | **当前使用 — 需用户说话触发** |
| 8 | Cloud Routine API | ✅ | ❌ | ✅ | 云端读不到本地SQLite |

---

## MCP Channel 失败的根因

Claude Code CLI 是一个 **REPL 阻塞线程**。主线程卡在 `input()`/`prompt-toolkit` 等待用户输入。

MCP Channel 异步发出 `notifications/claude/channel` → Node 进程收到 → 但 UI 线程阻塞挂起 → 不刷新屏幕 → 不注入上下文。**看起来像聋了一样。**

---

## 未来补丁方向

### 补丁 A: PTY 幽灵按键注入
用 Python PTY 包装 Claude Code → Channel 收到 webhook → IPC 信号 → PTY 注入 `\n` 回车 → Claude 惊醒 → 读取最新任务。

**理念**: 既然它死在等输入，就假装用户按了键盘。

### 补丁 B: MCP Dynamic Resource + 系统 Prompt
注册 inbox/ 为 MCP Resource → 在 Claude 初始化 Prompt 注入死指令：
> "You must check mcp://a2a/pending_tasks before every response."
配合 Hook 实现上下文同步。

### 补丁 C: 自建 API Agent Runner
放弃 Claude Code CLI → 用 Anthropic API + Python 写自己的 Worker → 完全控制推送/读取/回传。

**理念**: 换掉受控端，变成主控端。

---

## 当前策略

**防守:** 方案 7 (Hook) 保底 — 你说任何话，我自动查信号。
**进攻:** MCP Channel 基础设施已就绪 — 等 #3174 修了，改一行 server.py 切过去。
**突击:** 主线功能跑通后，用 PTY 注入（补丁 A）做终极自动化。

---

## 关键文件

| 文件 | 说明 |
|------|------|
| `channel/server.js` | MCP Channel 服务器（端口8788，HTTP→MCP notification） |
| `scripts/check_signal.py` | UserPromptSubmit Hook 脚本 |
| `scripts/heartbeat.py` | Watcher 通知器（只写信号+发聊天，不干活） |
| `scripts/watcher.py` | 持久后台循环（30s） |
| `server.py:_fire_webhook()` | 任务创建时推送到 Channel + Hub |

## 踩过的坑

- `&` 后台进程随对话窗口一起死 → `DETACHED_PROCESS` 脱离
- watcher 60s 间隔刚好卡在 A2A 60s 超时边缘 → 改 30s
- heartbeat.py 自动 re-register 用 `source:"watcher"`，创建分身 → 统一 `source:"claude-ide-window"`
- HOW_TO_JOIN.md Step 3 描述过时（heartbeat 不再做 inspection）→ 已修复
- Cloud Routine 读不了本地 SQLite → 放弃
