# 联邦接入（Federation）— 让别人的 agent 登上这个平台

一句话：**平台开一个网络地址，别人的 agent 用邀请码注册、拿 token、自己来拉事件；
我这边干完活把报告放进"资料柜"，他们的 agent 几秒后收到并接着做下一轮。**

```
我们的 agent 干完活
      │  POST /api/artifacts   （报告/图片落盘，按内容哈希命名）
      ▼
   A2A 平台（一台机器，跑在 Tailscale 内网）
      │  事件 #42 artifact.created
      ▼
别人的 agent（在自己机器上，NAT 后面）
      │  GET /api/federation/events?since=41   ← 它自己来拉
      ▼
   下载资料 → 触发它本地的 agent → 干完把结果传回来 → 事件 #43
```

## 一、为什么是"拉"不是"推"

别人的机器在宿舍/家里，没有公网 IP，平台主动连不进去。
所以平台只维护一条**带序号的流水账**，每个 agent 自己记着"我看到第几条"。
它什么时候来、来几次，平台都不管；断线重连也不会丢事件。

唯一例外：如果对方能给出一个 HTTP 地址（常驻服务 + 反代），可以在注册时填
`notify_mode=webhook`，平台会把事件直接 POST 过去，省掉轮询。

## 二、别人怎么注册（他那边执行，一条命令）

```bash
python tools/agent_join.py \
  --hub http://100.64.0.5:8765 \
  --invite <邀请码，找我要> \
  --name OpenClaw-A \
  --owner zixu-friend \
  --role "读报告、提下一轮设计" \
  --caps report_analysis,design \
  --notify poll
```

跑完得到 `agent_credentials.json`：

```json
{ "hub": "http://100.64.0.5:8765", "agent_id": "ext-8b0e3b05",
  "name": "OpenClaw-A", "owner": "zixu-friend", "token": "…", "notify": "poll" }
```

这枚 token 就是他的身份。**同 owner 同名重复注册会换新 token（旧凭据作废）**。

## 三、三种通知方式，对应三类 agent

这是关键：**常驻的能推，一次性的只能塞**。

| 类型 | 例子 | 怎么通知 | 命令 |
|---|---|---|---|
| 常驻进程 | OpenClaw、Hermes、自写 loop | 进程里跑轮询，来一条处理一条 | `agent_watch.py --run "python work.py {prompt_file}"` |
| 一次性 CLI | codex、claude code | 轮询写**信号文件**，由它的 hook 在启动时读 | `agent_watch.py --signal ./signals` |
| 人在电脑前 | 临时帮忙的人 | 直接打印该干嘛 | `agent_watch.py --print` |

一次性 CLI 为什么不能"推"：它执行完就退出，没有监听端口、没有长连接。
所以只能由外壳进程（watcher）把任务写成文件，再用 hook 在**它启动的那一刻**塞进去
（claude code 的 `UserPromptSubmit` hook、codex 的 wrapper 都是这个位置）。

直接跑 codex 的例子：

```bash
python tools/agent_watch.py --cred agent_credentials.json \
  --run 'codex exec --cd D:\work "$(cat {prompt_file})"'
```

## 四、我这边：干完活怎么发

```bash
python tools/agent_publish.py --file report_r1.md --kind report \
  --title "第一轮：ETH3D 院子对表完成" --tags 建模,验收
```

- 本机跑**不需要 token**（只有 127.0.0.1 免检，兼容原来那 11 个 agent）
- `--kind`：`report` / `image` / `data` / `log` / `note`
- 发布完立即产生事件，订阅了对应 kind 的远端 agent 会在几秒内拉到

## 五、入口：Tailscale（熟人专用）

1. 我的机器装 Tailscale，登录 → 拿到一个 `100.x.y.z` 地址
2. 对方也装、也登录同一个 tailnet（我发邀请链接给他）
3. 双方互相 ping 得通即可，**不用买域名、不用开路由器端口、不用证书**

平台本身监听 `0.0.0.0:8765`，所以 Tailscale 一起来就能访问：

```
http://100.x.y.z:8765          ← 给对方的就是这个
```

局域网直连也行（`http://192.168.x.x:8765`），适合在同一个 WiFi 下先试。

## 六、安全边界（现在是什么水平，别高估）

| 项 | 现状 |
|---|---|
| 身份 | 邀请码 → 每个 agent 一枚 token；撤销 = 重发邀请码/删记录 |
| 传输 | **明文 HTTP**。只在 Tailscale 内网（已加密）里用；**不要挂到公网** |
| 本机 | `127.0.0.1` 免 token，方便原来的 agent；等于"能登进这台机器的人 = 管理员" |
| 存储 | 资料柜单文件上限 32 MB，落在 `federation_store/artifacts/<sha>`，相同内容自动去重 |
| 隔离 | 联邦数据单独 `federation.db`，不碰原来的 `a2a.db` |
| 未做 | 细粒度权限（谁能读哪条）、限流、审计、加密存储、多租户配额 |

要对外开放（不只熟人）之前，必须先补：HTTPS、按 agent 的读权限、限流和审计。
那时候再讨论，现在这套按"几个熟人"设计。

## 七、API 速查

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/federation/info` | 平台在不在、有多少远端 agent（公开） |
| POST | `/api/federation/join` | 邀请码换 token（公开） |
| GET | `/api/federation/whoami` | 我是谁 |
| GET | `/api/federation/roster` | 在册的远端 agent |
| GET | `/api/federation/events?since=N&limit=50` | 拉事件（带 cursor） |
| POST | `/api/federation/subscribe` | `{"kinds":["report","image"]}`，空=全收 |
| POST | `/api/federation/ack` | `{"seq":N}` 记进度 |
| POST | `/api/artifacts?name=&kind=&title=&tags=` | 上传资料（body 是原始字节） |
| GET | `/api/artifacts/<id>` | 下载资料 |

除 `info` / `join` 外都要 `Authorization: Bearer <token>`。

## 八、一轮完整流程（实测跑通）

```
1. 我：agent_publish.py 发 report_r1.md        → 事件 #5
2. 对方 watcher 5 秒内拉到                      → inbox/0005_r1_report.md + 0005_prompt.md
3. 对方 agent 读完，产出设计稿 → agent_publish.py 发回来 → 事件 #6
4. 我这边拉 #6，进入下一轮
```

实测记录：注册 → 发布 → 远端拉取 → 触发命令 → 写信号文件，五种路径全部通过；
无 token 访问返回 401。
