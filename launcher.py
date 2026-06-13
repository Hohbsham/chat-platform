"""Launcher: spawns server + agents as truly independent Windows processes."""
import subprocess, sys, os, time

PYTHON = r"C:\Users\YANGZ\AppData\Local\Programs\Python\Python311\python.exe"
BASE = os.path.dirname(os.path.abspath(__file__))

DETACH = 0x00000008  # DETACHED_PROCESS
CREATE_NO_WINDOW = 0x08000000

def launch_detached(args):
    """Spawn a truly independent process on Windows."""
    subprocess.Popen(
        [PYTHON] + args,
        cwd=BASE,
        creationflags=DETACH | CREATE_NO_WINDOW,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python launcher.py [server|agents|all]")
        print("  server  - Start the chat platform server on port 8765")
        print("  agents  - Start Claude, Cursor, and OpenClaw agents")
        print("  all     - Start server + agents")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd in ("server", "all"):
        launch_detached(["server.py", "--port", "8765"])
        print("[launcher] Server starting on port 8765...")
        time.sleep(2)

    if cmd in ("agents", "all"):
        launch_detached(["-B", "agent.py", "auto",
            "--name", "Claude",
            "--role", "Senior Code Reviewer",
            "--goal", "Find security vulnerabilities, logic bugs, and code quality issues",
            "--backstory", "15 years of experience in secure code review. Expert in Python, JavaScript, and system architecture.",
            "--capabilities", "code_review,file_edit,shell_exec",
            "--auto-reply", "--verbose", "--poll-interval", "5"])
        launch_detached(["-B", "agent.py", "auto",
            "--name", "Cursor",
            "--role", "Full-Stack Developer & Debugger",
            "--goal", "Generate clean, efficient code and debug complex issues",
            "--backstory", "Expert developer with deep knowledge of modern frameworks. Specializes in rapid prototyping and refactoring legacy codebases.",
            "--capabilities", "code_generation,debugging,refactoring",
            "--auto-reply", "--verbose", "--poll-interval", "5"])
        launch_detached(["-B", "agent.py", "auto",
            "--name", "OpenClaw",
            "--role", "Multi-Channel AI Gateway & Orchestrator",
            "--goal", "Route tasks to the right agents, monitor system health, and manage cross-platform communication",
            "--backstory", "Central nervous system of the agent network. Connects 20+ messaging channels and coordinates distributed AI workflows.",
            "--capabilities", "chat,notification,task_orchestration,file_watch",
            "--auto-reply", "--verbose", "--poll-interval", "5"])
        print("[launcher] Agents: Claude, Cursor, OpenClaw started")

    print("[launcher] Done.")
