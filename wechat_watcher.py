"""
WeChat File Watcher Agent
Monitors WeChat file directories and auto-creates tasks for new files.

Usage:
  python wechat_watcher.py [--interval 30]

Requires: pip install watchdog
"""
import os, sys, time, json, urllib.request, hashlib

HOST = os.environ.get("CHAT_HOST", "http://localhost:8765")
# WeChat stores files in these Windows locations:
WATCH_DIRS = [
    os.path.expandvars(r"%USERPROFILE%\Documents\WeChat Files"),
    os.path.expandvars(r"%USERPROFILE%\Documents\Tencent Files"),
    r"D:\WeChat Files",
    r"C:\WeChat Files",
]

def api_post(path, data):
    url = f"{HOST}{path}"
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body,
        headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        return json.loads(urllib.request.urlopen(req).read())
    except Exception as e:
        return {"ok": False, "error": str(e)}

def file_hash(path):
    """Quick content hash for file dedup."""
    with open(path, "rb") as f:
        return hashlib.md5(f.read(1024)).hexdigest()  # First 1KB is enough

def scan_and_create(seen):
    """Scan for new files and create tasks."""
    for watch_dir in WATCH_DIRS:
        if not os.path.exists(watch_dir):
            continue
        for root, dirs, files in os.walk(watch_dir):
            for fname in files:
                fpath = os.path.join(root, fname)
                try:
                    # Skip system files, thumbs, small files
                    if fname.startswith('.') or fname.startswith('~'):
                        continue
                    size = os.path.getsize(fpath)
                    if size < 1024:  # Skip tiny files
                        continue

                    fhash = file_hash(fpath)
                    key = f"{fname}:{fhash}"
                    if key in seen:
                        continue
                    seen.add(key)

                    ext = fname.rsplit('.', 1)[-1].lower() if '.' in fname else ''
                    doc_types = {'pdf', 'docx', 'doc', 'pptx', 'xlsx', 'txt', 'md'}
                    img_types = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'}

                    if ext in doc_types:
                        title = f"审阅微信文件: {fname}"
                    elif ext in img_types:
                        title = f"分析微信图片: {fname}"
                    else:
                        continue

                    api_post("/api/tasks", {
                        "title": title,
                        "description": f"文件路径: {fpath}\n大小: {size/1024:.1f}KB",
                        "required_capabilities": ["paper_review"] if ext in doc_types else ["chat"],
                        "priority": "normal",
                        "creator": "WeChat-Watcher",
                        "broadcast": False,
                    })
                    print(f"[NEW] {fname} ({size/1024:.1f}KB) -> task created")
                except Exception as e:
                    pass  # Skip files that can't be accessed

def main():
    import argparse
    p = argparse.ArgumentParser(description="WeChat File Watcher")
    p.add_argument("--interval", type=int, default=30, help="Scan interval (seconds)")
    p.add_argument("--once", action="store_true", help="Scan once and exit")
    args = p.parse_args()

    # Find valid watch dir
    valid = [d for d in WATCH_DIRS if os.path.exists(d)]
    if not valid:
        print("No WeChat file directories found. Checked:")
        for d in WATCH_DIRS:
            print(f"  {d} -> {'EXISTS' if os.path.exists(d) else 'MISSING'}")
        sys.exit(1)

    print(f"WeChat File Watcher — {len(valid)} directories")
    for d in valid:
        print(f"  {d}")
    print(f"Scan every {args.interval}s")

    seen = set()
    while True:
        try:
            scan_and_create(seen)
        except Exception as e:
            print(f"[ERROR] {e}")

        if args.once:
            break
        time.sleep(args.interval)

if __name__ == "__main__":
    main()
