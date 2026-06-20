"""
Public tunnel for A2A Platform.
Supports: serveo.net (custom subdomain, no login) and localhost.run (free/nokey).

Usage:
  python tunnel.py --subdomain yangz-a2a              # Serveo (default)
  python tunnel.py --subdomain yangz-a2a --port 8765
  python tunnel.py --subdomain yangz-a2a --backend localhost.run  # fallback
"""
import subprocess, sys, time, re, os

PORT = "8765"
BACKEND = "serveo"
SUBDOMAIN = ""

# Parse args: --port, --subdomain, --backend
args = sys.argv[1:]
i = 0
while i < len(args):
    if args[i] == "--port" and i + 1 < len(args):
        PORT = args[i + 1]
        i += 2
    elif args[i] == "--subdomain" and i + 1 < len(args):
        SUBDOMAIN = args[i + 1]
        i += 2
    elif args[i] == "--backend" and i + 1 < len(args):
        BACKEND = args[i + 1]
        i += 2
    else:
        i += 1

if not SUBDOMAIN:
    print("Usage: python tunnel.py --subdomain <name> [--port 8765] [--backend serveo|localhost.run]")
    print("Example: python tunnel.py --subdomain yangz-a2a")
    sys.exit(1)

# ── Backend configs ─────────────────────────────────────────
BACKENDS = {
    "serveo": {
        "cmd": f'ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=30 '
               f'-R {SUBDOMAIN}:80:localhost:{PORT} serveo.net',
        "url_pattern": r'https?://' + re.escape(SUBDOMAIN) + r'\.serveo\.net',
        "label": f"https://{SUBDOMAIN}.serveo.net",
    },
    "localhost.run": {
        "cmd": f'ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=30 '
               f'-R 80:localhost:{PORT} nokey@localhost.run',
        "url_pattern": r'https?://[a-zA-Z0-9.-]+\.lhr\.life',
        "label": "(random, check output)",
    },
}

if BACKEND not in BACKENDS:
    print(f"Unknown backend: {BACKEND}. Options: {', '.join(BACKENDS.keys())}")
    sys.exit(1)

cfg = BACKENDS[BACKEND]
cmd = cfg["cmd"]

print(f" A2A Tunnel")
print(f"   Backend:    {BACKEND}")
print(f"   Local:      localhost:{PORT}")
print(f"   Target URL: {cfg['label']}")
print()

# ── Test SSH connection first ───────────────────────────────
test_cmd = f'ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 -o BatchMode=yes -v {SUBDOMAIN}@serveo.net 2>&1' if BACKEND == "serveo" else 'echo ok'
# Actually just run the tunnel directly, serveo gives feedback

try:
    proc = subprocess.Popen(
        cmd, shell=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1
    )

    url_found = False
    for line in proc.stdout:
        line_print = line.strip()
        if line_print:
            print(f"  {line_print}")

        # Try to find URL
        m = re.search(cfg["url_pattern"], line)
        if m and not url_found:
            url_found = True
            print()
            print("=" * 60)
            print(f"  PUBLIC URL: {m.group(0)}")
            print("  用手机或外部设备打开这个地址访问 A2A 平台")
            print("=" * 60)
            print()
            print("按 Ctrl+C 关闭隧道")

    proc.wait()

except KeyboardInterrupt:
    print("\n隧道已关闭。")
except FileNotFoundError:
    print("ERROR: SSH 未找到。请在 Windows 设置中安装 OpenSSH 客户端。")
    print("设置 → 应用 → 可选功能 → OpenSSH 客户端")
except Exception as e:
    print(f"ERROR: {e}")
