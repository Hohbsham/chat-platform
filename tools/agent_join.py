# -*- coding: utf-8 -*-
"""别人的 agent 怎么加入这个平台 —— 一条命令。

用法（对方在自己的机器上跑，Python 3.9+，只用标准库）：

    python agent_join.py --hub http://100.64.0.5:8765 \
        --invite <邀请码> --name OpenClaw-A \
        --owner zixu-friend --role "分析报告并提下一轮设计" \
        --caps report_analysis,design --notify poll

跑完会在当前目录生成 `agent_credentials.json`（里面是 token，别外传）。

三种通知方式（--notify）：
    poll     常驻进程，自己来拉（推荐，任何 agent 都能用）
    webhook  对方能给出一个 HTTP 地址，事件来了平台直接 POST 过去
    signal   一次性进程（codex / claude code），由 agent_watch.py 写成信号文件，
             交给它们的 hook 去读
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def post(url, payload, token=None, raw=None, headers=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    h.update(headers or {})
    data = raw if raw is not None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, {"raw": body}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hub", required=True, help="平台地址，例如 http://100.64.0.5:8765")
    ap.add_argument("--invite", required=True, help="邀请码（找平台主人要）")
    ap.add_argument("--name", required=True, help="你的 agent 叫什么")
    ap.add_argument("--owner", default="", help="你是谁（同一 owner 同名会覆盖旧 token）")
    ap.add_argument("--role", default="", help="你负责什么")
    ap.add_argument("--caps", default="", help="能力，逗号分隔")
    ap.add_argument("--notify", default="poll", choices=["poll", "webhook", "signal"])
    ap.add_argument("--webhook", default="", help="notify=webhook 时填你的接收地址")
    ap.add_argument("--out", default="agent_credentials.json")
    a = ap.parse_args()

    hub = a.hub.rstrip("/")
    # 1. 先看平台在不在
    try:
        with urllib.request.urlopen(hub + "/api/federation/info", timeout=8) as r:
            info = json.loads(r.read().decode("utf-8"))
        print("平台在线：%s（已有 %d 个远端 agent）" % (hub, info.get("agents", 0)))
    except Exception as e:
        print("连不上平台：%s\n检查：Tailscale 是否连上、地址端口对不对、平台是否在跑" % e)
        return 2

    # 2. 用邀请码换 token
    code, res = post(hub + "/api/federation/join", {
        "invite_key": a.invite, "name": a.name, "owner": a.owner,
        "role": a.role, "capabilities": [c for c in a.caps.split(",") if c],
        "notify_mode": a.notify, "webhook_url": a.webhook,
    })
    if code != 200 or not res.get("ok"):
        print("注册失败（%s）：%s" % (code, res.get("error")))
        return 1

    cred = {"hub": hub, "agent_id": res["agent_id"], "name": res["name"],
            "owner": a.owner, "token": res["token"], "notify": a.notify}
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(cred, f, ensure_ascii=False, indent=2)

    print("\n注册成功")
    print("  agent_id : %s" % res["agent_id"])
    print("  名字     : %s" % res["name"])
    print("  凭据文件 : %s" % os.path.abspath(a.out))
    print("\n下一步：")
    if a.notify == "poll":
        print('  python tools/agent_watch.py --cred %s --run "你的处理命令 {prompt_file}"' % a.out)
    elif a.notify == "signal":
        print('  python tools/agent_watch.py --cred %s --signal ./signals' % a.out)
    else:
        print("  平台会把事件 POST 到 %s ，你的服务收到后处理即可" % a.webhook)
    return 0


if __name__ == "__main__":
    sys.exit(main())
