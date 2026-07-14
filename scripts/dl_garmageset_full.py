import os
"""GarmageSet full downloader — 256 raw shards, 4 workers, resume support."""
import urllib.request, socket, os, time, sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

PROXY = "http://127.0.0.1:7897"
TOKEN = os.environ.get("HF_TOKEN", "")
BASE = "https://huggingface.co/datasets/Style3D/GarmageSet/resolve/main"
DL = Path("D:/ClothesNetData/garmageset_download")
WORKERS = 4
SHARD_NAMES = [f"{i:02x}" for i in range(256)]

# Setup
proxy_handler = urllib.request.ProxyHandler({"http": PROXY, "https": PROXY})
urllib.request.install_opener(urllib.request.build_opener(proxy_handler))
socket.setdefaulttimeout(180)
DL.mkdir(parents=True, exist_ok=True)

def download_shard(name):
    url = f"{BASE}/raw/{name}.tar.gz"
    out = DL / f"raw_{name}.tar.gz"
    # Skip if already complete (>50KB means valid)
    if out.exists() and out.stat().st_size > 50000:
        return name, "skip", out.stat().st_size
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
            with urllib.request.urlopen(req, timeout=600) as resp:
                data = resp.read()
            out.write_bytes(data)
            return name, "ok", len(data)
        except Exception as e:
            if attempt < 2:
                time.sleep(5 * (attempt + 1))
            else:
                return name, f"fail:{e}", 0

# Main
print(f"GarmageSet: {len(SHARD_NAMES)} shards, {WORKERS} workers")
start = time.time()
ok, skip, fail = 0, 0, 0
done_names = set()

with ThreadPoolExecutor(max_workers=WORKERS) as pool:
    futures = {pool.submit(download_shard, n): n for n in SHARD_NAMES}
    for i, f in enumerate(as_completed(futures)):
        name, status, size = f.result()
        if status == "ok":
            ok += 1
            print(f"[{i+1:3d}/256] {name}: {size/1024/1024:.0f}MB OK")
        elif status == "skip":
            skip += 1
        else:
            fail += 1
            print(f"[{i+1:3d}/256] {name}: {status}")
        if (ok + skip + fail) % 20 == 0:
            elapsed = time.time() - start
            total_mb = sum(p.stat().st_size for p in DL.glob("raw_*.tar.gz") if p.stat().st_size > 50000) / 1024 / 1024
            print(f"  --- {ok+skip+fail}/256 ({ok} new, {skip} cached, {fail} fail), {total_mb:.0f}MB, {elapsed:.0f}s ---")

elapsed = time.time() - start
total_mb = sum(p.stat().st_size for p in DL.glob("raw_*.tar.gz") if p.stat().st_size > 50000) / 1024 / 1024
print(f"\nDONE: {ok} OK, {skip} cached, {fail} FAIL in {elapsed/60:.1f}min")
print(f"Total: {total_mb:.0f}MB in {DL}")
