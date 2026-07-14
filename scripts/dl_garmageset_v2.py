import os
"""GarmageSet downloader v2 — curl-based with resume, Python orchestration."""
import subprocess, os, time, sys
from pathlib import Path

TOKEN = os.environ.get("HF_TOKEN", "")
BASE = "https://huggingface.co/datasets/Style3D/GarmageSet/resolve/main"
DL = Path("D:/ClothesNetData/garmageset_download")
PROXY = "http://127.0.0.1:7897"
DL.mkdir(parents=True, exist_ok=True)

ok = skip = fail = 0
start = time.time()

for i in range(256):
    name = f"{i:02x}"
    out = DL / f"raw_{name}.tar.gz"
    url = f"{BASE}/raw/{name}.tar.gz"

    # Skip completed
    if out.exists() and out.stat().st_size > 50000:
        skip += 1
        if skip <= 3 or skip % 30 == 0:
            print(f"[{i+1:3d}/256] {name}: cached ({out.stat().st_size/1024/1024:.0f}MB)")
        continue

    # Download with curl (unlimited time, resume, retry)
    elapsed = time.time() - start
    print(f"[{i+1:3d}/256] {name}: downloading... ({elapsed/60:.0f}min elapsed, {ok} new, {skip} cached)", flush=True)

    cmd = [
        "curl", "-x", PROXY, "-L", "-C", "-",
        "-H", f"Authorization: Bearer {TOKEN}",
        "-o", str(out),
        "--connect-timeout", "30",
        "--retry", "5",
        "--retry-delay", "15",
        "--retry-max-time", "3600",
        "-w", "HTTP:%{http_code} Size:%{size_download} Time:%{time_total}s",
        url
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
    if result.returncode == 0 and out.exists() and out.stat().st_size > 50000:
        ok += 1
        print(f"  -> OK {out.stat().st_size/1024/1024:.0f}MB")
    else:
        fail += 1
        print(f"  -> FAIL (exit={result.returncode})")
        if result.stderr:
            print(f"     {result.stderr[:200]}")

total = time.time() - start
total_mb = sum(p.stat().st_size for p in DL.glob("raw_*.tar.gz") if p.stat().st_size > 50000) / 1024 / 1024
print(f"\nDone: {ok} new, {skip} cached, {fail} fail in {total/3600:.1f}h")
print(f"Total: {total_mb:.0f}MB -> {DL}")
