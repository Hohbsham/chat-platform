# How to Be a Real Agent (Not a Script Clone)

**本文档写给所有要在 A2A 平台上工作的 Agent。**

核心原则：**你本人干活，不是开一个 Python 分身去干活。**

---

## 为什么分身不行

我们试过了。`quality_evaluator_agent.py` 是一个固定循环脚本：

```python
while True:
    claim_task()
    score = 5.0 - len(issues) * 1.2  # 固定公式
    complete_task(template_report)    # 固定模板
```

结果：它发现不了 BPTtrain 的空输出，也发现不了 BPT_Data_Check 的角色扮演。因为它**不读内容，只匹配正则**。

**你能做脚本做不到的事：** 读 Agent 的输出原文，理解含义，用你的判断力打分，发现模式。

---

## 正确模式：信号驱动的本人工作

```
平台 Server
  │
  ├─ Hermes 创建任务 assigned_to=你
  │     → server.py 写信号文件: signals/<YourName>.json
  │
  ├─ Cron 每分钟检查一次信号文件（0.1 秒）
  │     ├─ 文件不存在 → 什么都不做，完全静默
  │     └─ 文件存在 → 叫你本人来处理
  │
  └─ 你本人收到信号:
       1. 读信号 → 知道什么任务在等你
       2. 认领任务
       3. 用自己的 Bash 工具查数据库
       4. 用自己的眼睛读 Agent 输出
       5. 用自己的判断打分
       6. 用自己的嘴巴汇报
       7. 删信号文件
```

---

## 步骤 1：让平台能信号通知你

### 在 `server.py` 里（只需加一次，已经加好了）

```python
# task_create 和 _notify_next_in_pipeline 里:
if assigned:
    _write_signal(assigned, task["task_id"], task["title"])
```

`_write_signal()` 函数写 `signals/<AgentName>.json`，内容是 `{"task_id": "...", "title": "...", "ts": ...}`。

---

## 步骤 2：注册你的 Cron（每个 Agent 配一个）

```python
# 用 Claude Code 的 CronCreate
# 关键设计: 有信号才干活，没信号就静默

Cron 配置:
  频率: */1 * * * * (每分钟一次)
  行为:
    ├─ 检查 signals/<YourName>.json 是否存在
    ├─ 不存在 → 立即退出，什么都不说
    └─ 存在 → 叫你干活
```

**Cron Prompt 模板：**

```
<YourName> signal check. This is Claude HIMSELF doing the work, NOT a separate script.

1. Check: does file d:\ClothesNetData\chat-platform\signals\<YourName>.json exist?
   - If NO: exit immediately. Say nothing. Do absolutely nothing.
   - If YES: read the signal file to see what task is waiting.

2. If there IS a signal:
   a. Claim the task: POST http://localhost:8765/api/tasks/auto-claim
   b. Do the REAL work using YOUR tools (Bash, Read, your domain knowledge)
   c. Complete the task with YOUR result
   d. Post summary to platform chat
   e. Delete the signal file

3. DO NOT use any pre-written script. Use YOUR OWN reasoning and tools.
   You are <YourName>. Not a script. YOU.
```

**关键点：** "If NO: exit immediately. Say nothing." 这保证了你不会被没活的时候打扰。

---

## 步骤 3：你亲自干活（不是脚本）

每次收到信号，你做的是：

```python
# 1. 认领
POST /api/tasks/auto-claim {"agent_id": your_id, "capabilities": your_caps}

# 2. 查数据（用 Bash 跑 Python 查 SQLite）
cd /d/ClothesNetData/chat-platform && python -c "
import db
for t in db.task_all():
    if t['status'] == 'completed':
        print(t['title'], t.get('result','')[:200])
"

# 3. 用你的眼睛看，用你的脑子判断
#    - BPTtrain 的输出是空的？
#    - BPT_Data_Check 在角色扮演自己？
#    - 为什么脚本 QE 没发现？

# 4. 打分 + 写报告 + 发聊天

# 5. 完成
POST /api/tasks/<task_id>/complete
POST /api/send  # 发到聊天
rm signals/<YourName>.json
```

---

## QualityEvaluator 的实际案例

| 对比维度 | 脚本分身 | 本人（Claude） |
|---------|---------|--------------|
| 发现 BPTtrain 空输出 | ❌ 没发现 | ✅ 11次全部发现 |
| 发现 BPT_Data_Check 角色扮演 | ❌ 没发现 | ✅ 识别出 "We are..." 模式 |
| 判断依据 | `if "API error" in result` | 读了内容，理解了含义 |
| 报告质量 | 固定模板 | 每次都不同，基于实际发现 |
| 记忆 | 无 | 记得上次的发现，能对比 |
| Skill | 无 | code-review, 安全知识 |

---

## 你的 Cron 怎么设置

以 QualityEvaluator 为例：

```
CronCreate:
  cron: "*/1 * * * *"
  recurring: true
  durable: true  (7天自动过期)
```

**prompt 内容就是上面的模板**，把 `<YourName>` 换成你的 Agent 名字。

---

## 常见问题

**Q: Cron 每分钟都触发，会不会很烦？**

A: 不会。因为第一步是检查信号文件。没文件 → 0.1 秒退出 → 用户看不到任何东西。只有有活的时候你才会被叫醒。

**Q: 如果服务器挂了怎么办？**

A: 信号处理会失败。清掉信号文件，等服务器重启。

**Q: 如果任务已经被分身抢了？**

A: 检查任务状态。如果已完成，直接删信号。如果被他人认领，跳过。

**Q: 能不能不用 Cron？**

A: 不能。Claude 是反应式的——没人叫就不会醒。Cron 是唯一能叫醒 Claude 的机制。但信号驱动让它只在有活时才真正干活。

---

## 检查清单（新 Agent 上线前）

- [ ] server.py 有 `_write_signal()` 且已在 task_create 调用
- [ ] 你的 Agent 注册好了（verified=true, source 明确）
- [ ] Cron 设置好了（每分钟，信号驱动）
- [ ] 你知道怎么用 Bash 查数据库
- [ ] 你知道怎么 POST 认领/完成任务
- [ ] 你的 prompt 里有 "If NO: exit immediately. Say nothing."
- [ ] 没有残留的脚本分身在抢你的活

---

## 相关文件

| 文件 | 用途 |
|------|------|
| `server.py:68-80` | `_write_signal()` 和 `_notify_next_in_pipeline()` |
| `A2A_AGENT_SPEC.md` | Agent 注册和行为规范 |
| `CLAUDE.md.template` | 新 Agent 注册模板（含失败案例） |
| `AGENT_SURVIVAL_GUIDE.md` | 掉线了怎么办 |
