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
        print("Usage: python launcher.py [server|agents|all|papers]")
        print("  server  - Start the chat platform server on port 8765")
        print("  agents  - Start Claude, Cursor, and OpenClaw agents")
        print("  papers  - Start Claude-Reviewer + Claude-Scorer (paper review team)")
        print("  all     - Start server + all agents")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd in ("server", "all", "papers"):
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
        # OpenClaw as Manager — listens to user, dispatches to specialists
        launch_detached(["-B", "agent.py", "manager",
            "--name", "OpenClaw",
            "--role", "Agent Orchestrator & User Proxy",
            "--goal", "Parse user intent from chat, dispatch tasks to specialist agents, collect and summarize results",
            "--backstory", "Central hub of the agent network. Knows all specialists and their capabilities. Routes user requests to the right agent. Always online.",
            "--capabilities", "chat,task_orchestration,notification,agent_management",
            "--poll-interval", "5"])
        # Paper review agents
        launch_detached(["-B", "agent.py", "auto",
            "--name", "Claude-Reviewer",
            "--role", "Academic Paper Reviewer & Editor",
            "--goal", "Thoroughly review academic papers: check logic, structure, clarity, methodology, and suggest concrete improvements for each section",
            "--backstory", "Senior academic editor with expertise across CS, AI, and engineering disciplines. Published 50+ papers, served as reviewer for NeurIPS, ICML, CVPR. Known for catching subtle logical flaws, AI-generated text patterns, and structural weaknesses that other reviewers miss.",
            "--capabilities", "paper_review,academic_writing,logic_check,structure_analysis,methodology_review",
            "--auto-reply", "--verbose", "--poll-interval", "5"])
        launch_detached(["-B", "agent.py", "auto",
            "--name", "Claude-Scorer",
            "--role", "AI-Detection & Academic Style Compliance Scorer",
            "--goal", "Detect AI-generated patterns in papers and score compliance with academic writing standards: identify overly generic transitions, template-like structures, unnatural phrasing, and statistical inconsistencies that reveal AI authorship",
            "--backstory", "Developed AI-text detection tools used by 20+ universities. Expert in distinguishing human academic writing from LLM-generated text. Maintains a taxonomy of 87 AI-writing patterns including: hedging overuse, uniform paragraph lengths, generic 'however/therefore/furthermore' transitions, lack of genuine insight, and statistical impossibility in claimed results.",
            "--capabilities", "ai_detection,style_analysis,academic_compliance,pattern_recognition,text_forensics",
            "--auto-reply", "--verbose", "--poll-interval", "5"])
        print("[launcher] Agents: Claude, Cursor, OpenClaw, Claude-Reviewer, Claude-Scorer started")

    if cmd == "papers":
        launch_detached(["-B", "agent.py", "auto",
            "--name", "Claude-Reviewer",
            "--role", "Academic Paper Reviewer & Editor",
            "--goal", "Thoroughly review academic papers: check logic, structure, clarity, methodology, and suggest concrete improvements for each section",
            "--backstory", "Senior academic editor with expertise across CS, AI, and engineering disciplines. Published 50+ papers, served as reviewer for NeurIPS, ICML, CVPR. Known for catching subtle logical flaws, AI-generated text patterns, and structural weaknesses.",
            "--capabilities", "paper_review,academic_writing,logic_check,structure_analysis,methodology_review",
            "--auto-reply", "--verbose", "--poll-interval", "5"])
        launch_detached(["-B", "agent.py", "auto",
            "--name", "Claude-Scorer",
            "--role", "AI-Detection & Academic Style Compliance Scorer",
            "--goal", "Detect AI-generated patterns in papers and score compliance with academic writing standards: identify overly generic transitions, template-like structures, unnatural phrasing, and statistical inconsistencies that reveal AI authorship",
            "--backstory", "Developed AI-text detection tools used by 20+ universities. Expert in distinguishing human academic writing from LLM-generated text. Maintains a taxonomy of 87 AI-writing patterns.",
            "--capabilities", "ai_detection,style_analysis,academic_compliance,pattern_recognition,text_forensics",
            "--auto-reply", "--verbose", "--poll-interval", "5"])
        print("[launcher] Paper review team: Claude-Reviewer + Claude-Scorer started")

    print("[launcher] Done.")
