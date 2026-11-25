# -*- coding: utf-8 -*-
"""在别人的机器上跑：拉事件 → 下资料 → 触发他本地的 agent。

为什么是"拉"：对方在 NAT 后面，平台推不进去。这个进程每 5 秒问一句
`/api/federation/events?since=N`，有新东西就干活。

三种落地方式，对应三类 agent：

  1) 常驻型（OpenClaw / Hermes / 自己写的 loop）
     --run "python handle.py {prompt_file}"
     进程一直在，来一条事件跑一次。

  2) 一次性型（codex / claude code 这种一问一答的 CLI）
     --run 'codex exec --cd D:\\work "$(cat {prompt_file})"'
     或者 --signal ./signals —— 只写一个信号 json 文件，交给它们的 hook
     （claude code 的 UserPromptSubmit hook、codex 的 wrapper）自己来读。
     这是关键：一次性进程没法被"推"，只能由外壳进程在它启动时把任务塞进去。

  3) 完全没有 hook 的（人在电脑前）
     --print   直接把该做什么打到终端

用法：
    python agent_watch.py --cred agent_credentials.json --print
    python agent_watch.py --cred agent_credentials.json --run "python work.py {prompt_file}"
    python agent_watch.py --cred agent_credentials.json --signal D:\\work\\signals
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request

TEMPLATE = """# 来自平台的第 {seq} 条事件

- 类型：{type}
- 谁发的：{actor}
- 标题：{title}
- 资料：{artifact_line}

## 资料内容位置
{prompt_hint}

## 你要做的
{instruction}
"""


def api_get(url, token, raw=False):
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = r.read()
    return data if raw else json.loads(data.decode("utf-8"))


def api_post(url, token, payload):
    req = urllib.request.Request(
        url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": "Bearer " + token,
                 "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cred", default="agent_credentials.json")
    ap.add_argument("--interval", type=float, default=5.0, help="几秒拉一次")
    ap.add_argument("--inbox", default="inbox", help="资料下载目录")
    ap.add_argument("--once", action="store_true", help="只拉一次就退出（适合 cron）")
    ap.add_argument("--print", dest="do_print", action="store_true")
    ap.add_argument("--run", default="", help="收到事件要执行的命令，支持 {prompt_file} 等占位符")
    ap.add_argument("--signal", default="", help="写信号文件的目录（给 CLI 型 agent 的 hook 读）")
    ap.add_argument("--instruction", default="读上面的资料，按你们约定的流程做下一轮，做完把结果上传回平台。")
    ap.add_argument("--kinds", default="", help="只订阅这些事件类型，逗号分隔；空=全收")
    a = ap.parse_args()

    with open(a.cred, "r", encoding="utf-8") as f:
        cred = json.load(f)
    hub, token, name = cred["hub"].rstrip("/"), cred["token"], cred["name"]
    aid = cred["agent_id"]

    cursor_file = os.path.join(os.path.dirname(os.path.abspath(a.cred)),
                               ".cursor_%s.json" % aid)
    since = 0
    if os.path.exists(cursor_file):
        try:
            since = int(json.load(open(cursor_file)).get("since", 0))
        except Exception:
            since = 0

    if a.kinds:
        api_post(hub + "/api/federation/subscribe", token,
                 {"kinds": [k for k in a.kinds.split(",") if k]})
        print("已订阅：%s" % a.kinds)

    os.makedirs(a.inbox, exist_ok=True)
    if a.signal:
        os.makedirs(a.signal, exist_ok=True)

    print("[%s] 盯着 %s，从 #%d 之后开始，每 %.0f 秒一次" % (name, hub, since, a.interval))

    while True:
        try:
            data = api_get("%s/api/federation/events?since=%d" % (hub, since), token)
        except Exception as e:
            print("拉取失败（会自动重试）：%s" % e)
            if a.once:
                return 1
            time.sleep(max(a.interval, 10))
            continue

        for ev in data.get("events", []):
            seq = ev["seq"]
            art = ev.get("artifact") or {}
            art_path = ""
            if art.get("id"):
                try:
                    body = api_get(hub + "/api/artifacts/" + art["id"], token, raw=True)
                    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_"
                                   for ch in (art.get("name") or "file"))
                    art_path = os.path.join(a.inbox, "%04d_%s" % (seq, safe))
                    with open(art_path, "wb") as f:
                        f.write(body)
                except Exception as e:
                    print("下载资料失败：%s" % e)

            prompt = TEMPLATE.format(
                seq=seq, type=ev.get("type"), actor=ev.get("actor"),
                title=ev.get("title") or "",
                artifact_line=(("%s（%s, %d 字节）" % (art.get("name"), art.get("kind"),
                                                     art.get("size", 0)))
                               if art else "无"),
                prompt_hint=(art_path or "（本条事件没有附资料）"),
                instruction=a.instruction)
            pfile = os.path.join(a.inbox, "%04d_prompt.md" % seq)
            with open(pfile, "w", encoding="utf-8") as f:
                f.write(prompt)

            stamp = "%s #%d %s" % (time.strftime("%H:%M:%S"), seq, ev.get("title"))

            if a.do_print or not (a.run or a.signal):
                print("\n" + "=" * 60)
                print(prompt)

            if a.signal:
                sig = os.path.join(a.signal, "%s.json" % name.replace("/", "_"))
                with open(sig, "w", encoding="utf-8") as f:
                    json.dump({"agent": name, "seq": seq, "event": ev,
                               "prompt_file": pfile, "artifact": art_path,
                               "at": time.time()}, f, ensure_ascii=False, indent=2)
                print("%s → 信号已写 %s" % (stamp, sig))

            if a.run:
                cmd = (a.run.replace("{prompt_file}", pfile)
                            .replace("{artifact}", art_path)
                            .replace("{inbox}", os.path.abspath(a.inbox))
                            .replace("{seq}", str(seq))
                            .replace("{title}", ev.get("title") or ""))
                print("%s → 执行：%s" % (stamp, cmd))
                try:
                    subprocess.run(cmd, shell=True)
                except Exception as e:
                    print("命令失败：%s" % e)

            since = seq
            with open(cursor_file, "w") as f:
                json.dump({"since": since}, f)

        if data.get("events"):
            try:
                api_post(hub + "/api/federation/ack", token, {"seq": since})
            except Exception:
                pass

        if a.once:
            return 0
        time.sleep(a.interval)


if __name__ == "__main__":
    sys.exit(main())
