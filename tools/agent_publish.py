# -*- coding: utf-8 -*-
"""我这边干完活 → 把资料放进平台 → 自动通知订阅的远端 agent。

用法：
    python tools/agent_publish.py --file report_r1.md --kind report --title "第一轮：ETH3D 对表完成"
    python tools/agent_publish.py --file shot.png --kind image --title "立面截图" --tags 建模,验收

本机跑不用 token（平台对本机免验证）；从别的机器发布则加 --cred。
"""
import argparse
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hub", default="http://127.0.0.1:8765")
    ap.add_argument("--file", required=True)
    ap.add_argument("--kind", default="report",
                    choices=["report", "image", "data", "log", "note"])
    ap.add_argument("--title", default="")
    ap.add_argument("--tags", default="")
    ap.add_argument("--cred", default="", help="远端发布时用 agent_credentials.json")
    a = ap.parse_args()

    if not os.path.exists(a.file):
        print("没有这个文件：%s" % a.file)
        return 1

    token = ""
    if a.cred:
        token = json.load(open(a.cred, encoding="utf-8"))["token"]

    body = open(a.file, "rb").read()
    name = os.path.basename(a.file)
    headers = {"Content-Type": "application/octet-stream"}
    if token:
        headers["Authorization"] = "Bearer " + token

    qs = urllib.parse.urlencode({"name": name, "kind": a.kind,
                                 "title": a.title or name, "tags": a.tags})
    url = a.hub.rstrip("/") + "/api/artifacts?" + qs
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print("上传失败 %s：%s" % (e.code, e.read().decode("utf-8", "replace")))
        return 1

    print("已发布：%s" % res["artifact_id"])
    print("  文件 : %s（%.1f KB）" % (name, len(body) / 1024))
    print("  标题 : %s" % (a.title or name))
    print("  下载 : %s/api/artifacts/%s" % (a.hub.rstrip("/"), res["artifact_id"]))
    print("  订阅了 report/image 的远端 agent 会在几秒内拉到它。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
