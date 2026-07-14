import os
"""GarmageSet v3 — per-shard timeout, skip-and-retry, no hang."""
import subprocess, time, sys
from pathlib import Path

TOKEN = os.environ.get("HF_TOKEN", "")
BASE = "https://huggingface.co/datasets/Style3D/GarmageSet/resolve/main"
DL = Path("D:/ClothesNetData/garmageset_download")
PROXY = "http://127.0.0.1:7897"
TIMEOUT = 600  # 10 min per shard max
DL.mkdir(parents=True, exist_ok=True)

def dl_one(i):
    name = f"{i:02x}"
    out = DL / f"raw_{name}.tar.gz"
    url = f"{BASE}/raw/{name}.tar.gz"

    # Skip if complete (>50KB)
    if out.exists() and out.stat().st_size > 50000:
        return name, "skip", out.stat().st_size

    cmd = [
        "curl", "-x", PROXY, "-L", "-C", "-",
        "-H", f"Authorization: Bearer {TOKEN}",
        "-o", str(out),
        "--connect-timeout", "20",
        "--max-time", str(TIMEOUT),
        "--retry", "2",
        "--retry-delay", "10",
        "-w", "HTTP:%{http_code}",
        url
    ]

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT + 60)
        if r.returncode == 0 and out.exists() and out.stat().st_size > 50000:
            return name, "ok", out.stat().st_size
        err = r.stderr[:100] if r.stderr else "unknown"
        return name, f"fail({r.returncode})", out.stat().st_size if out.exists() else 0
    except subprocess.TimeoutExpired:
        return name, "timeout", out.stat().st_size if out.exists() else 0
    except Exception as e:
        return name, f"err:{e}", out.stat().st_size if out.exists() else 0

# Main
print("GarmageSet v3 — 10min/shard timeout, auto-skip")
ok = skip = fail = 0
failed_list = []
start = time.time()

for i in range(256):
    name, status, size = dl_one(i)
    elapsed = time.time() - start

    if status == "ok":
        ok += 1
        print(f"[{i+1:3d}/256] {name}: {size/1024/1024:.0f}MB OK ({elapsed/60:.0f}min)")
    elif status == "skip":
        skip += 1
        if skip <= 3 or skip % 30 == 0:
            print(f"[{i+1:3d}/256] {name}: {size/1024/1024:.0f}MB cached [{skip} cached]")
    else:
        fail += 1
        failed_list.append(name)
        print(f"[{i+1:3d}/256] {name}: {status} [{fail} fail so far]")

total_mb = sum(p.stat().st_size for p in DL.glob("raw_*.tar.gz") if p.stat().st_size > 50000) / 1024 / 1024
print(f"\nPass 1 done: {ok} new, {skip} cached, {fail} fail in {elapsed/60:.0f}min, {total_mb:.0f}MB")

# Retry failed
if failed_list:
    print(f"\nRetrying {len(failed_list)} failed: {failed_list}")
    for name in failed_list:
        i = int(name, 16)
        _, status, size = dl_one(i)
        if status in ("ok", "skip"):
            fail -= 1
            ok += 1
            print(f"  {name}: RECOVERED ({size/1024/1024:.0f}MB)")
        else:
            print(f"  {name}: still failed")

total_mb = sum(p.stat().st_size for p in DL.glob("raw_*.tar.gz") if p.stat().st_size > 50000) / 1024 / 1024
print(f"\nFinal: {ok} new, {skip} cached, {fail} failed, {total_mb:.0f}MB in {DL}")
