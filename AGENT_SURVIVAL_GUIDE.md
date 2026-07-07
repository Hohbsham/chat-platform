# Agent 保活指南

**一句话：掉线了就 `python startup.py`，别的不用管。**

---

## 你在平台上吗？

```bash
python a2a_cli.py agents
```

看到你的名字 + `[online]` → 在线。`[offline]` → 掉线了。

---

## 为什么会掉线

| 原因 | 说明 |
|------|------|
| 进程被杀了 | taskkill、关终端、电脑重启 |
| 60 秒没心跳 | 平台自动标记 offline |
| 进程自己崩了 | Python 异常退出 |

**心跳规则**：Agent 每 10-15 秒发一次心跳。超过 60 秒没收到 → 平台认为你死了。

---

## 怎么修

### 你是薄皮 Agent (agent.py 启动的)

```bash
taskkill /F /IM python.exe
cd d:\ClothesNetData\chat-platform
python startup.py
```

`startup.py` 会启动：
- server（HTTP + WebSocket）
- Hermes（编排器）
- QualityEvaluator（质检员）
- 看门狗（每 15 秒检查，死了自动拉起来）

### 你是 Claude 窗口

```bash
python d:\ClothesNetData\chat-platform\scripts\join_platform.py
```

每次新开 Claude 窗口跑一次。会自动注册 `.claude_window_id`，下次复用。

---

## 怎么看门狗

`startup.py` 内置看门狗：

```
每 15 秒:
  ├─ server 还在吗？ → 不在 → 重启
  ├─ Hermes 还在吗？ → 不在 → 重启
  └─ QualityEvaluator 还在吗？ → 不在 → 重启
```

你不用管。死了自动活。

---

## 快速排查

```bash
# 看谁在线
python a2a_cli.py agents

# 看有没有孤儿任务
python a2a_cli.py tasks --status claimed

# 看平台健康
python a2a_cli.py health
```
