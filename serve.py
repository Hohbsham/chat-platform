"""Single-entry server launcher that keeps the process alive.
Usage: python serve.py [--port 8765]
"""
import subprocess, sys, os, time, json

PYTHON = sys.executable
BASE = os.path.dirname(os.path.abspath(__file__))
PORT = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--port" else "8765"

# Reset data
for f in ['agents.json', 'tasks.json', 'messages.json']:
    with open(os.path.join(BASE, f), 'w', encoding='utf-8') as fp:
        json.dump([], fp)

# Start server as a proper child process with its own console
server_proc = subprocess.Popen(
    [PYTHON, os.path.join(BASE, 'server.py'), '--port', PORT],
    cwd=BASE,
    creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == 'win32' else 0,
)

print(f"Server PID: {server_proc.pid}")
print(f"HTTP: http://localhost:{PORT}")
print(f"WS:   ws://localhost:{int(PORT)+1}")

# Wait for server to be ready
import urllib.request
for i in range(10):
    time.sleep(2)
    try:
        resp = urllib.request.urlopen(f'http://localhost:{PORT}/api/health', timeout=3)
        print(f"Server ready (after {(i+1)*2}s)")
        break
    except Exception:
        pass

# Now start agents
for name, role, goal, backstory, caps in [
    ("Claude", "Senior Code Reviewer",
     "Find security vulnerabilities, logic bugs, and code quality issues",
     "15 years of experience in secure code review.",
     "code_review,file_edit,shell_exec"),
    ("Cursor", "Full-Stack Developer & Debugger",
     "Generate clean, efficient code and debug complex issues",
     "Expert in modern frameworks. Rapid prototyping specialist.",
     "code_generation,debugging,refactoring"),
    ("OpenClaw", "Multi-Channel AI Gateway & Orchestrator",
     "Route tasks, monitor health, coordinate distributed workflows",
     "Central hub for agent network. 20+ channel integrations.",
     "chat,notification,task_orchestration,file_watch"),
]:
    subprocess.Popen(
        [PYTHON, '-B', os.path.join(BASE, 'agent.py'), 'auto',
         '--name', name, '--role', role, '--goal', goal, '--backstory', backstory,
         '--capabilities', caps, '--auto-reply', '--verbose', '--poll-interval', '5'],
        cwd=BASE,
        creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == 'win32' else 0,
    )
    print(f"Agent {name} started")

print("\nAll services running. Press Ctrl+C to stop server.")
try:
    server_proc.wait()
except KeyboardInterrupt:
    server_proc.terminate()
    print("Shutdown.")
