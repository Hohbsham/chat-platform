"""Watchdog: keep restarting dl_garmageset_v3 until all 256 done."""
import subprocess, time, sys
from pathlib import Path

DL = Path("D:/ClothesNetData/garmageset_download")
SCRIPT = Path(__file__).parent / "dl_garmageset_v3.py"
TARGET = 256

while True:
    count = len(list(DL.glob("raw_*.tar.gz")))
    total_mb = sum(p.stat().st_size for p in DL.glob("raw_*.tar.gz")) / 1024 / 1024
    print(f"[{time.strftime('%H:%M:%S')}] {count}/{TARGET} shards, {total_mb:.0f}MB", flush=True)

    if count >= TARGET:
        print("ALL DONE!", flush=True)
        break

    print(f"  Launching downloader...", flush=True)
    r = subprocess.run(
        [sys.executable, "-u", str(SCRIPT)],
        cwd=str(DL.parent),
        timeout=7200  # 2h max per run
    )
    print(f"  Downloader exited: {r.returncode}", flush=True)
    time.sleep(3)
