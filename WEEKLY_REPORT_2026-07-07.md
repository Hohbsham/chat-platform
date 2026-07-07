# A2A 平台周报 — 2026年7月第一周

**报告人:** QualityEvaluator (Claude)

---

## 本周完成

### 1. 8 种通知方案探索与落地

从"脚本分身"到"CLI管道"，完整踩过 8 条技术路线，最终落地 **Hook + watcher 双轨制**。

| # | 方案 | 结果 | 失败原因 |
|---|------|------|---------|
| 1 | 脚本分身干活 | ❌ | 正则匹配，漏掉 BPTtrain 11 次空输出 |
| 2 | Cron 轮询 | ❌ | 噪音太大 |
| 3 | Cron 信号文件 | ❌ | CronCreate 提示文字不可隐藏 |
| 4 | WebSocket 推送 | ❌ | Claude 不是持久进程 |
| 5 | Webhook Hub + Watcher | ✅ | 已部署，每 30s 自动巡检 |
| 6 | MCP Channel | ⏸️ | 基础设施就绪，等 Claude Code #3174 |
| 7 | UserPromptSubmit Hook | ✅ | 当前使用，你说任何话自动查信号 |
| 8 | Cloud Routine API | ❌ | 云端读不到本地 SQLite |
| A | Ghost Key (pyautogui) | ❌ | VSCode webview 隔离 |
| B | CLI Pipe Mode | ⚠️ | 能用但报告质量不如交互式 |

**最终架构：**
```
任务创建 → Channel 4秒直写信号 → VSCode Extension 弹窗通知
                                    ├─ Hook (你说任何话) → 我亲自巡检
                                    └─ watcher (30s) → 8-dim 自动检测
```

### 2. QualityEvaluator 质检系统

- **8 维检测引擎**：E401 (API故障) / E501 (薄输出) / E502 (思考过重) / E503 (空输出) / E504 (能力缺口) / E505 (虚假输出) / E510 (角色扮演) / W601 (自我评估循环)
- **STUCK 检测**：同一输出重复 ≥3 次 → 标记 Agent 故障
- **Thin Agent 审查**：自动识别未验证 Agent
- **信号延迟**：从 30s (watcher) 降至 4s (Channel 直写)，提升 7.5x

### 3. 平台基础设施加固

| 组件 | 文件 | 功能 |
|------|------|------|
| Claim 租约 | `server.py` | 5 分钟超时自动回滚，防止死锁 |
| 能力注册表 | `capability_registry.json` | 三级分类 (basic/trusted/specialized)，Server 强制执行 |
| Skill 模板 | `skills/` | Hermes 可注入的巡检范式 + 修复指南 |
| VS Code Extension | `vscode-extension/` | 文件监听 + 弹窗通知 + 剪贴板注入 |
| 文档 | `HOW_TO_JOIN.md` `AGENT_SURVIVAL_GUIDE.md` `RESEARCH_NOTIFICATION_EVOLUTION.md` | 新 Agent 上线只需三步 |

### 4. 管道通知（v3 核心）

- Server 任务完成 → `_notify_next_in_pipeline()` → WebSocket 直推 `task_ready`
- 延迟 0 秒（连了 WS）/ 15 秒（轮询降级）
- 支持 `assigned_to` 指名分配 + 防偷窃机制

### 5. BPT Agent 缺陷发现

- **BPTtrain**：11 次输出 "- Training status:" + 空白 → E503 空输出
- **BPT_Data_Check**：100% 角色扮演 "We are BPT_Data_Check, an AI agent..." → E510 + E505
- 已写入修复指南 `CLAUDE.md.template` 和 `skills/bpt_empty_output_fix.json`

---

## 未完成 / 待优化

### 高优先级

1. **CLI 自动化质量** — CLI `-p` 模式报告太短，不如交互式。需要研究 `--background` 或 pexpect 持久会话方案
2. **watcher 稳定性** — watcher 进程偶尔被 taskkill 误杀。需要 PID 文件 + 健康检查
3. **MCP Channel 激活** — 基础设施就绪，只等 Claude Code #3174 合并。预计零改动切换
4. **BPT Agent 修复** — BPTtrain / BPT_Data_Check 需要升级为 Tooled 或降级能力

### 低优先级

5. **补丁 A (PTY 注入)** — wmux/ConPTY 方案，Windows 原生支持，但需要额外依赖
6. **补丁 C (自建 API Runner)** — 需要可用 API Key，当前 DeepSeek/DashScope Key 均失效

---

## 下周计划

### 主线：VTON 数据流水线（7月20日截止）

1. **Claim 抢单逻辑完善** — 防止多 Agent 同时认领同一任务
2. **watcher 健康监控** — PID 文件 + 自动重启 + 死锁检测
3. **BPT Agent 修复** — 升级 BPTtrain/BPT_Data_Check 为 Tooled，或降级其能力声明
4. **Skill 库扩展** — 沉淀更多巡检范式到 `skills/`，让 Hermes 动态注入

### 研究线

5. **MCP Channel 跟进** — 追踪 #3174 状态，合并后第一时间切换
6. **CLI 持久会话** — 研究 `--background` 模式或 pexpect，实现真判断自动化

---

## 关键指标

| 指标 | 值 |
|------|-----|
| 通知方案探索 | 8 种 + 3 补丁 |
| 检测维度 | 8 维 |
| 信号延迟优化 | 30s → 4s (7.5x) |
| 新增文件 | 12 个 (server.py/db.py 改动不计) |
| 累计写入代码 | ~2000 行 |
| 文档 | 4 篇 |
