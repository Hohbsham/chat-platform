"""Kill all, restart platform + watcher terminal."""
import subprocess, os, time, sys, urllib.request, json

BASE = r'd:\ClothesNetData\chat-platform'

# Kill all python/pythonw
for exe in ['python.exe', 'pythonw.exe']:
    r = subprocess.run(f'tasklist /FI "IMAGENAME eq {exe}" /FO CSV /NH', shell=True, capture_output=True, text=True)
    for line in r.stdout.splitlines():
        parts = line.split(',')
        if len(parts) > 1:
            pid = parts[1].strip('"')
            subprocess.run(f'taskkill /PID {pid} /F', shell=True, capture_output=True)
            print(f'Killed {pid}')

time.sleep(3)

# Clean signals
sig_dir = os.path.join(BASE, 'signals')
os.makedirs(sig_dir, exist_ok=True)
for f in os.listdir(sig_dir):
    if f.endswith('.json') or f.endswith('.done'):
        p = os.path.join(sig_dir, f)
        try: os.remove(p)
        except: pass
        print(f'Cleaned: {f}')

# Start services
for script in ['webhook_hub.py', 'server.py']:
    args = [sys.executable, os.path.join(BASE, script)]
    if 'server' in script:
        args += ['--port', '8765']
    subprocess.Popen(args, cwd=BASE,
                     creationflags=0x00000008|0x08000000,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f'Started {script}')

time.sleep(5)
r = json.loads(urllib.request.urlopen('http://localhost:8765/api/health', timeout=10).read())
print(f'Server OK, agents={r["agents_online"]}')

# Open watcher terminal
subprocess.Popen(f'start "A2A Watcher" cmd /k "cd /d {BASE} && python scripts\\desktop_watcher.py"',
                 shell=True, cwd=BASE)
print('Watcher terminal opened')
