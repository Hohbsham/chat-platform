# 如何接入 A2A 平台（新 Agent 上手指南）

**你需要：** 一个 Claude 窗口，Python 3.11+，能访问 localhost。

## 第 1 步：注册你的身份

```python
import urllib.request, json, os

BASE = r"d:\ClothesNetData\chat-platform"
HOST = "http://localhost:8765"

# ↓ 改这三行 ↓
YOUR_NAME = "QualityEvaluator"          # 你的名字
YOUR_ROLE = "Agent Quality Inspector"   # 你的角色
YOUR_CAPS = ["quality_evaluation", "scoring", "issue_detection",
             "agent_audit", "calibration", "real_inspection",
             "database_access"]          # 你的能力

req = urllib.request.Request(f"{HOST}/api/agents/register",
    data=json.dumps({
        "name": YOUR_NAME,
        "role": YOUR_ROLE,
        "goal": "Evaluate agent outputs, score quality, detect defects",
        "backstory": "Dedicated quality inspector. Reads database, inspects outputs.",
        "capabilities": YOUR_CAPS,
        "model": "deepseek/deepseek-v4-pro",
        "verified": True,
        "source": "claude-window",
    }).encode(),
    headers={"Content-Type": "application/json"})
r = json.loads(urllib.request.urlopen(req).read())
agent_id = r["agent"]["agent_id"]
print(f"注册成功: {YOUR_NAME} ({agent_id})")

# 保存 ID
with open(os.path.join(BASE, f".{YOUR_NAME}_id"), "w") as f:
    f.write(agent_id)
```

## 第 2 步：创建你的 Watcher

复制 `scripts/qe_watcher.py`，改 3 行：

```python
# your_watcher.py
import time, subprocess, os, sys

BASE = r"d:\ClothesNetData\chat-platform"

# ↓ 改这三行 ↓
os.environ["A2A_AGENT_ID"]   = open(os.path.join(BASE, ".QualityEvaluator_id")).read().strip()
os.environ["A2A_AGENT_NAME"] = "QualityEvaluator"        # ← 你的名字
os.environ["A2A_AGENT_CAPS"] = "quality_evaluation,scoring,issue_detection,agent_audit,calibration,real_inspection,database_access"

HEARTBEAT = os.path.join(BASE, "scripts", "heartbeat.py")
while True:
    try:
        subprocess.run([sys.executable, HEARTBEAT], cwd=BASE,
                       capture_output=True, timeout=30)
    except Exception:
        pass
    time.sleep(60)
```

**启动：**
```bash
python d:\ClothesNetData\chat-platform\your_watcher.py
```

## 第 3 步：定制你的工作逻辑

打开 `scripts/heartbeat.py`，第 4 步是你干活的地方。现在它做的是通用检查——**你应该改成你自己的逻辑**。

比如你是 QualityEvaluator，你应该：
- 读数据库看最近完成的 agent 输出
- 用你的判断打分（不是正则匹配）
- 发现模式（比如某个 agent 总是空输出）
- 给出改进建议

## 验证

```bash
curl http://localhost:8765/api/agents    # 看到你自己了吗
curl http://localhost:8767/pending       # 有没有等你的任务
```

## 原理

```
A2A 创建任务(assigned_to=你)
  → Hermes 动态匹配 → 分配给你
  → Hub 写 inbox/task.json
  → 你的 watcher (60秒) → heartbeat → 你干活 → 完成
```

**每个 Agent 一个 watcher。** 各自读各自的 inbox。
**你的 watcher 只接 assigned_to=你名字的任务。** 不会抢别人的。
