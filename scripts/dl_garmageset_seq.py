import os
"""GarmageSet sequential downloader — reliable, auto-resume."""
import urllib.request, socket, os, time, sys
from pathlib import Path

PROXY = "http://127.0.0.1:7897"
TOKEN = os.environ.get("HF_TOKEN", "")
BASE = "https://huggingface.co/datasets/Style3D/GarmageSet/resolve/main"
DL = Path("D:/ClothesNetData/garmageset_download")

proxy_handler = urllib.request.ProxyHandler({"http": PROXY, "https": PROXY})
urllib.request.install_opener(urllib.request.build_opener(proxy_handler))
socket.setdefaulttimeout(180)
DL.mkdir(parents=True, exist_ok=True)

ok = skip = fail = 0
start = time.time()

for i in range(256):
    name = f"{i:02x}"
    out = DL / f"raw_{name}.tar.gz"

    if out.exists() and out.stat().st_size > 50000:
        skip += 1
        if skip % 20 == 0:
            print(f"[{skip:3d} cached] {name}")
        continue

    url = f"{BASE}/raw/{name}.tar.gz"
    sys.stdout.write(f"[{i+1:3d}/256] {name}: ")
    sys.stdout.flush()

    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
            resp = urllib.request.urlopen(req, timeout=300)
            data = resp.read()
            out.write_bytes(data)
            print(f"{len(data)/1024/1024:.0f}MB OK")
            ok += 1
            break
        except Exception as e:
            if attempt < 2:
                time.sleep(5)
            else:
                print(f"FAIL ({e})")
                fail += 1

elapsed = time.time() - start
total_mb = sum(p.stat().st_size for p in DL.glob("raw_*.tar.gz") if p.stat().st_size > 50000) / 1024 / 1024
print(f"\nDone: {ok} new, {skip} cached, {fail} fail in {elapsed/60:.0f}min")
print(f"Total: {total_mb:.0f}MB -> {DL}")
