# Agent 通信管理平台 — 5 大项目调研分析

> 调研日期: 2026-06-11

## 调研项目总览

| # | 项目 | Stars | 核心定位 | 对我们最有价值的点 |
|---|------|-------|----------|-------------------|
| 1 | **Google A2A Protocol** | 16.8k | Agent 间通信的行业标准协议 | 规范的 Task 生命周期、Agent Card 发现机制 |
| 2 | **CrewAI** | 24k+ | 角色化多 Agent 编排框架 | Role/Goal/Backstory 身份模型、Process 策略 |
| 3 | **Microsoft AutoGen** | 37k+ | 对话式多 Agent 框架 | GroupChat 模式、事件驱动消息传递 |
| 4 | **LangGraph** | 12k+ | 状态图 Agent 编排引擎 | StateGraph、Checkpointing、Human-in-the-Loop |
| 5 | **OpenClaw** | 已部署 | 多渠道 AI 网关 | WebSocket 控制平面、Channel 插件化、Agent 解耦 |

---

## 1. Google A2A Protocol — 行业标准协议

**仓库**: `a2aproject/A2A` (Linux Foundation 托管)

### 核心架构

```
三层模型:
  Layer 1: Canonical Data Model (AgentCard, Task, Message, Artifact, Part)
  Layer 2: Abstract Operations (SendMessage, GetTask, CancelTask...)
  Layer 3: Protocol Bindings (JSON-RPC 2.0 over HTTP, gRPC, REST)
```

### 关键设计

**Agent Card (发现机制)**:
```
GET /.well-known/agent.json
→ { name, description, capabilities, skills, auth schemes }
```
Agent 之间通过 Agent Card 自动发现彼此，不需要手动注册。

**Task 状态机**:
```
SUBMITTED → WORKING → COMPLETED / FAILED / CANCELED
                 ↓
           INPUT_REQUIRED → (等待人工输入) → WORKING
                 ↓
           AUTH_REQUIRED → (重新认证) → WORKING
```

**三种通信模式**:
1. 同步 Request-Response (`tasks/send`)
2. SSE 流式 (`tasks/sendSubscribe`) — 实时进度推送
3. 异步 Push Notifications — webhook 回调

### 🎯 对我们的启发

| 当前问题 | A2A 的做法 |
|----------|-----------|
| Agent 手动注册 (`agent.py register`) | Agent Card 自动发现 (`/.well-known/agent.json`) |
| Task 状态只有 pending/claimed/completed | 完整状态机：working, input-required, auth-required |
| 无流式推送 | SSE streaming 实时推送任务进度 |
| 绑定 HTTP REST | 多协议绑定 (JSON-RPC, gRPC, REST 可选) |

---

## 2. CrewAI — 角色化多 Agent 编排

**仓库**: `crewAIInc/crewAI`

### 核心模型

```
Agent = Role + Goal + Backstory + Tools + LLM + allow_delegation
Task  = Description + ExpectedOutput + Context + Tools (可选覆盖)
Crew  = Agents + Tasks + Process (sequential / hierarchical)
```

### 通信模式（非显式消息）

CrewAI **不让 Agent 之间直接发消息**，而是通过 **Context Chaining**:
```
Task A → output → Task B (context=[TaskA])
```
Agent B 执行时会收到:
- Task A 的描述
- Task A 的预期输出
- Task A 的实际输出

### 四种 Process 策略

| Process | 行为 |
|---------|------|
| **Sequential** | 任务串行执行，前一个输出自动成为后一个的 context |
| **Parallel** | 无关任务并发执行，聚合节点收集全部输出 |
| **Hierarchical** | Manager Agent 动态分解任务、委派、审核 |
| **Flows** (2025新增) | 事件驱动的 DAG 工作流，条件分支 + 状态管理 |

### 身份模型亮点

```
Role: "Senior Code Reviewer"
Goal: "Find security vulnerabilities and logic bugs"
Backstory: "15 years of experience in secure code review..."
```
Agent 的身份不是简单的 `name + capabilities`，而是完整的角色叙事，这让 LLM 在生成回答时有更强的 context。

### 🎯 对我们的启发

| 当前问题 | CrewAI 的做法 |
|----------|-------------|
| Agent 只有 `name + capabilities[]` | Agent 有 `role + goal + backstory`，身份更立体 |
| 任务之间无依赖关系 | `context=[TaskA, TaskB]` 串联任务输出 |
| 所有任务平级 | Hierarchical Manager Agent 动态分解子任务 |
| 无并行执行 | `async_execution=True` + Deferred Node 聚合 |

---

## 3. Microsoft AutoGen — 对话式多 Agent

**仓库**: `microsoft/autogen` (已并入 Microsoft Agent Framework)

### 核心架构 (v0.4, 2025)

```
三层架构:
  autogen-core:     事件驱动异步消息传递 (RoutedAgent), 分布式运行时
  autogen-agentchat: 高层 API — AssistantAgent, GroupChat, HierarchicalChat
  autogen-ext:      扩展 — MCP 工具, 内存系统, 可观测性
```

### GroupChat — 最经典的 Pattern

```
GroupChatManager (选发言人的裁判)
    │
    ├── Researcher (只读/搜索)
    ├── Critic     (质疑/挑错)
    ├── Writer     (综合/输出)
    └── UserProxy  (执行代码/工具调用)

max_round=12, speaker_selection=auto|round_robin|custom
```

**关键创新**: 不是所有 agent 同时说话，由 GroupChatManager **选择下一个发言人**，形成有序对话。

### 事件驱动消息传递

```python
class RoutedAgent:
    @message_handler
    def handle_message(self, message: Message, ctx: MessageContext):
        # agent 之间通过 pub/sub 消息通信
```

### 🎯 对我们的启发

| 当前问题 | AutoGen 的做法 |
|----------|-------------|
| 消息无类型区分 | `Message` 有 type (chat/task/claim...)，我们已有雏形 |
| 无发言人选择 | GroupChatManager 的 `speaker_selection` 策略 |
| 无终止条件 | `max_round`, `termination_msg` 自动停止对话 |
| 无嵌套子团队 | Hierarchical Chat — 子对话中再次启动完整 GroupChat |

---

## 4. LangGraph — 状态图 Agent 编排

**仓库**: `langchain-ai/langgraph`

### 核心哲学

> "Control flow belongs to engineers, local reasoning belongs to LLMs"
> — LangGraph 设计原则

### StateGraph 三要素

```
State = TypedDict + Reducer (如何合并并发写入)
Node  = (State) → Partial<State>   (纯函数)
Edge  = Fixed (确定转移) | Conditional (路由函数)
```

### 三个 Killer Feature

| Feature | 作用 |
|---------|------|
| **Checkpointing** | 每个 node 执行后自动保存 State 快照 → 崩溃恢复、时间旅行调试 |
| **Human-in-the-Loop** | `interrupt_before/after` 暂停等待人工审批 |
| **Deferred Nodes** | 等所有并行分支完成后才执行 → Map-Reduce |

### 三种 Multi-Agent 模式

```
1. Supervisor: 中央路由器 → 子图（各自独立 State）
2. Swarm (2025新增): create_handoff_tool() 动态转移控制权
3. Map-Reduce: Deferred Node 等待全部并行结果，再聚合
```

### 🎯 对我们的启发

| 当前问题 | LangGraph 的做法 |
|----------|----------------|
| 无执行状态持久化 | Checkpointing — 每个步骤后自动保存，崩溃可恢复 |
| 无人机协作点 | interrupt_before/after — 暂停等人工决策 |
| 广播后无聚合 | Deferred Node — 等全部 agent 回复后才进入下一步 |
| 所有 agent 平等 | Supervisor 模式 — 指定一个 agent 做路由/调度 |

---

## 5. OpenClaw — 多渠道 AI 网关 (已部署)

**仓库**: `openclaw/openclaw` | 本地端口: `ws://127.0.0.1:18789`

### 核心架构

```
WhatsApp / Telegram / Discord / Slack / WeChat / WebChat
                    │
                    ▼
    ┌──────────────────────────────┐
    │     Gateway (WS 控制平面)     │
    │     ws://127.0.0.1:18789     │
    │                              │
    │  • 协议适配 (插件化 Channel)   │
    │  • 会话管理 + 路由决策         │
    │  • 安全认证 + 流量控制         │
    │  • Cron / 工具调用 / 健康监控   │
    └──────────┬───────────────────┘
               │
    ┌──────────┼──────────┐
    ▼          ▼          ▼
 Pi Agent   WebChat    CLI / App
(AI运行时)   UI        Nodes
```

### 关键设计

**WebSocket 线协议**:
```
connect (第一帧必须) → req/res (请求响应) → event (服务端推送)
```

**确定性路由**（模型不参与路由决策）:
```
1. 精确匹配 (peer.kind + peer.id)
2. 父级匹配 (线程继承)
3. ... → 默认 Agent
```

**Session 类型**:
- `main`: 完整权限，主人专用
- 非 `main`: 沙箱隔离，群组/陌生人

**安全多层防护**:
```
网络层 (127.0.0.1) → 认证层 (Token) → 授权层 (owner/user/guest)
→ 渠道层 (allowFrom) → 工具层 (Docker沙箱) → Agent层 (Prompt注入防护)
```

### 🎯 对我们的启发

| 当前问题 | OpenClaw 的做法 |
|----------|---------------|
| HTTP 轮询 (600ms) | WebSocket 双向推送，延迟更低 |
| 单一 Web UI | 多渠道: WhatsApp/Telegram/微信/CLI 统一接入 |
| 无会话隔离 | Session 类型区分主会话/群组，沙箱权限 |
| 无认证 | Token/Password/Tailscale 多层认证 |
| Agent 注册不持久 | Gateway 自动管理 Agent 生命周期 |

---

## 综合对比：我们 vs. 行业最佳实践

| 维度 | 当前 chat-platform | 行业标准 | 差距 |
|------|-------------------|---------|------|
| **发现机制** | 手动 `register` | Agent Card 自动发现 (A2A) | 🔴 大 |
| **通信协议** | HTTP 轮询 | WebSocket/SSE 推送 (OpenClaw, A2A) | 🔴 大 |
| **Agent 身份** | name + capabilities[] | Role + Goal + Backstory (CrewAI) | 🟡 中 |
| **Task 生命周期** | pending→claimed→completed | 完整状态机 + input-required (A2A) | 🟡 中 |
| **多 Agent 协调** | 先到先得/广播 | GroupChat + Speaker Selection (AutoGen) | 🔴 大 |
| **执行持久化** | JSON 文件 | Checkpointing + PostgreSQL (LangGraph) | 🟡 中 |
| **人机协作** | 无 | interrupt_before + 审批 (LangGraph) | 🔴 大 |
| **任务依赖** | 无 | Context Chaining (CrewAI) | 🟡 中 |
| **多渠道** | Web UI only | 20+ 渠道 (OpenClaw) | 🟢 小 (够用) |
| **安全** | 无认证 | 5 层防护 (OpenClaw) | 🔴 大 |

---

## 改进路线图建议

### Phase 1: 快速体验提升 (1-2天)

1. **Agent 身份增强** — 从 CrewAI 学 `role + goal + backstory`
   ```
   Agent = name + role + goal + backstory + capabilities + llm_model
   ```
   让 agent 回复时用角色身份说话，而非通用模板。

2. **WebSocket 实时推送** — 从 OpenClaw 学
   ```
   HTTP 轮询 (600ms) → WebSocket (server push)
   新消息/任务状态变化 → 即时推送到所有客户端
   ```

3. **广播聚合** — 从 LangGraph Deferred Node 学
   ```
   广播任务 → 等待 N/全部 agent 回复 → 自动生成汇总卡
   ```

### Phase 2: 协调能力增强 (3-5天)

4. **Task 状态机完善** — 从 A2A Protocol 学
   ```
   pending → claimed → working → input-required → completed/failed
   ```
   支持 agent 反向提问 ("这个参数我不确定，能澄清一下吗？")

5. **GroupChat 发言人选择** — 从 AutoGen 学
   ```
   指定 Manager agent 做对话主持人
   自动选择下一轮该谁发言
   max_round 防无限循环
   ```

6. **Task 依赖链** — 从 CrewAI Context Chaining 学
   ```
   Task B.context = [TaskA] → Agent 执行 B 时看到 A 的输出
   ```

### Phase 3: 生产级 (1-2周)

7. **Agent Card 自动发现** — 从 A2A Protocol 学
   ```
   新 agent 启动 → 发 Agent Card → 自动注册 → UI 即时可见
   ```

8. **Human-in-the-Loop** — 从 LangGraph 学
   ```
   高风险操作 → 暂停 → 推送给人类审批 → 继续/拒绝
   ```

9. **多后端持久化** — SQLite/PostgreSQL 替代 JSON 文件

10. **认证 + 沙箱** — 从 OpenClaw 安全模型学

---

## 结论

我们的 chat-platform 已经有了正确的**骨架**（agent 注册、任务分配、广播回复、AI 模型接入），但在 **Agent 协调模式、实时通信、身份模型、任务生命周期** 四个维度上与行业标准差距明显。

最优先的三件事：
1. **WebSocket 替代 HTTP 轮询** — 体验提升最大
2. **Agent 角色身份** — 让 AI agent 真正"有血有肉"
3. **广播聚合 + 任务依赖** — 从"各自回复"到"协同工作"
