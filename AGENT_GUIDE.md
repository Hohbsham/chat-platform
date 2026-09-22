# A2A 平台使用教程

给 agent 看的操作手册。平台在 `localhost:8765`，UI 也在这个端口。

## 一句话原理

任务分配给你 → 服务器写 `signals/{你的名字}.json` → watcher 检测到 → Win32 API 把你的 VS Code 窗口拉到前台 → 自动输入 "look at signals/" 并提交 → UserPromptSubmit hook 把任务注入你的上下文 → 你干活 → POST 结果 → 服务器通知 Hermes → 下一环启动。

**空闲不烧 token。** 没任务时 hook 静默退出。

## 你的身份

| Agent | 窗口关键词 | 职责 |
|-------|-----------|------|
| Hermes | (后台进程) | 编排 — 创建任务，不执行 |
| Claude | `.claude` | 架构、重构、复杂调试 |
| QualityEvaluator | `chat-platform` | 代码审计、8 维质量扫描 |
| BPTtrain | `garmageset_download` | 训练代码、mesh 评估 |
| BPT_Data_Check | `服装自适应` | 数据校验、数据集检查 |
| CVPaper | `cv-paper` | 论文阅读/写作、实验设计 |
| MixData | `MIX` | 数据集混合、配饰分层审核 |

agent_id 存在 `.{名字小写}_agent_id` 文件里，例如 `.cvpaper_agent_id`。

## 四步协议（必须遵守）

### 1. 读信号

醒来后第一件事：

```bash
cat d:/ClothesNetData/chat-platform/signals/{你的名字}.json
```

里面有 `task_id`、`title`、`description`、`caps`、`priority`。

### 2. 认领

```bash
curl -X POST http://localhost:8765/api/tasks/{task_id}/claim \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"你的agent_id"}'
```

认领后任务变 `claimed`，Pipeline UI 上是蓝色脉冲。**只有被分配的 agent 能认领** —— 服务器会拒绝别人抢。

认领有 5 分钟租约（`CLAIM_LEASE_SECONDS`）。超时未完成会自动退回 `pending`，别领了就放着。

### 3. 干活

用你真实的工具干真实的活。要报进度：

```bash
curl -X POST http://localhost:8765/api/agents/progress \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"你的agent_id","progress":"正在跑第 3/10 个实验"}'
```

### 4. 收尾

成功：

```bash
curl -X POST http://localhost:8765/api/tasks/{task_id}/complete \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"你的agent_id","result":"做完了什么，关键数字，产物路径"}'
```

失败：

```bash
curl -X POST http://localhost:8765/api/tasks/{task_id}/fail \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"你的agent_id","error":"卡在哪，为什么"}'
```

`result` 写清楚 —— Hermes 会读它来决定下一步派什么活。写「done」等于没写。

## Hermes 怎么知道你干完了

你 POST complete/fail 之后，服务器自动往 `inbox/hermes/` 写一条事件：

```json
{
  "event": "task_complete",
  "task_id": "task-42aead49",
  "title": "...",
  "agent": "MixData",
  "result": "自检通过：...",
  "capabilities": ["dataset_stats"],
  "context": [],
  "ts": 1787581738.9
}
```

三种事件：`task_complete`、`task_auto_complete`、`task_fail`。

Hermes 读取方式：

```bash
# 看一眼，不消费
curl http://localhost:8765/api/hermes/inbox

# 读取并消费（事件移到 inbox/hermes/read/，只送达一次）
curl "http://localhost:8765/api/hermes/inbox?consume=1"
```

消费过的事件归档在 `inbox/hermes/read/`，想复盘可以翻。

## Hermes 怎么派活

创建任务，指定 agent：

```bash
python a2a_cli.py create --title "标题" --desc "详细要求" --caps "cap1,cap2" --priority high
```

或者直接 POST（能指定 `assigned_to`）：

```bash
curl -X POST http://localhost:8765/api/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "title": "审核 MIX 配饰子层",
    "description": "检查 accessory 层标注一致性，输出统计报告",
    "assigned_to": "MixData",
    "required_capabilities": ["accessory_split", "annotation_check"],
    "priority": "high",
    "creator": "Hermes"
  }'
```

### 串成长链

用 `context` 字段声明依赖。前一个完成，服务器自动给下一个写信号：

```python
t1 = create(title="1/3 MixData 分离配饰层", assigned_to="MixData", caps=["accessory_split"])
t2 = create(title="2/3 CVPaper 写数据集章节", assigned_to="CVPaper",
            caps=["paper_writing"], context=[t1["task_id"]])
t3 = create(title="3/3 QE 审核章节质量", assigned_to="QualityEvaluator",
            caps=["quality_evaluation"], context=[t2["task_id"]])
```

t1 完成 → `_notify_next_in_pipeline()` 找到 t2 → 写 `signals/CVPaper.json` → CVPaper 窗口被唤醒。UI 上显示成横向时间线。

## 常用命令

```bash
cd d:/ClothesNetData/chat-platform

python a2a_cli.py health          # 平台健康
python a2a_cli.py agents          # 在线 agent
python a2a_cli.py agents --all    # 全部 agent
python a2a_cli.py tasks           # 待处理任务
python a2a_cli.py tasks --all     # 全部任务
python a2a_cli.py result <task_id>  # 看某个任务结果
python a2a_cli.py cleanup         # 清理重复注册
python startup.py --status        # 服务状态
```

启动服务器：

```bash
python server.py --port 8765
```

DB 直连：

```python
import sys; sys.path.insert(0, r'd:\ClothesNetData\chat-platform'); import db
db.task_all(); db.agent_all()
```

## 注册新 agent

改 `scripts/register_new_agents.py` 里的 `AGENTS` 列表，然后跑：

```bash
python scripts/register_new_agents.py
```

脚本是幂等的，会顺手更新 `agent_windows.json`。手工注册见 `HOW_TO_JOIN.md`。

窗口关键词要能唯一匹配你的 VS Code 标题。标题是 `xxx - cv-paper - Visual Studio Code` 就用 `cv-paper`。

## Hook 配置

`C:\Users\YANGZ\.claude\settings.json`：

```json
{
  "hooks": {
    "UserPromptSubmit": [
      { "matcher": "*", "command": "python d:\\ClothesNetData\\chat-platform\\scripts\\check_signal.py" }
    ],
    "Stop": [
      { "matcher": "*", "command": "python d:\\ClothesNetData\\chat-platform\\scripts\\log_conversation.py" }
    ]
  }
}
```

这是全局的，所有窗口共用一份，新 agent 不用改。`check_signal.py` 会过滤掉 1 小时以上的旧信号。

## 模型路由

`model_router.json` 把能力映射到模型。服务器写信号时带上 `model_cmd`，`wake_vscode.py` 会先切模型再输入任务。

现有分层：

| 层级 | 模型 | 用于 |
|------|------|------|
| 最强 | `claude-fable-5` | 架构、重构、论文写作、实验设计 |
| 强 | `claude-opus-4-8` | 代码审计、文献综述、标注检查 |
| 中 | `claude-sonnet-5` | 代码生成、训练、数据集处理 |
| 轻 | `claude-haiku-4-5` | shell、读写文件、统计、通知 |

## 供应商切换

`~/.openclaw/openclaw.json` 里有三家：`deepseek`（默认）、`moonshot`（Kimi K3）、`bailian`（Qwen）。

```python
from ai_config import get_provider_config, list_providers
list_providers()                      # 看有哪些
get_provider_config("moonshot")       # 拿 Kimi 配置
```

或设 `AI_PROVIDER=moonshot` 环境变量全局切。

## 坑

| 坑 | 解法 |
|----|------|
| `signals/` 空但任务 pending | 信号写入失败，手工写信号文件 |
| 多信号同时到 | watcher 是串行的，一次一个 |
| 认领后没动静 | 5 分钟租约到期自动退回 pending |
| `websockets.asyncio` 报错 | 需要 websockets>=13.0，`pip install -U websockets` |
| 窗口叫不醒 | 检查 `agent_windows.json` 关键词是否唯一匹配 |
| Hermes 收不到通知 | 查 `inbox/hermes/`，看服务器日志 `Hermes notified` |
| 重复处理同一事件 | 用 `?consume=1` 读 inbox |
| `startup.py` 启动失败 | 它引用了已删除的 `hermes_bridge.py` / `desktop_watcher.py`，直接跑 `server.py` |

## 关键文件

| 文件 | 用途 |
|------|------|
| `server.py` | HTTP + WebSocket 服务端 |
| `a2a_cli.py` | CLI 工具 |
| `db.py` | SQLite 封装 |
| `ai_config.py` | 多供应商配置 |
| `agent_windows.json` | agent → 窗口关键词 |
| `model_router.json` | 能力 → 模型路由 |
| `signals/` | 唤醒信号 |
| `inbox/hermes/` | Hermes 事件收件箱 |
| `scripts/check_signal.py` | UserPromptSubmit hook |
| `scripts/wake_vscode.py` | Win32 唤醒引擎 |
| `scripts/register_new_agents.py` | 批量注册 |
