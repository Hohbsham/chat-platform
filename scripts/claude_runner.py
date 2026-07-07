"""
Claude Runner — Scheme B: Pipe Mode Automation.

Task arrives → spawn Claude CLI with -p → pipe task → capture output → complete A2A.
No persistent process. No clipboard. No focus stealing. Zero noise when idle.
"""
import os, json, time, subprocess, sys, urllib.request, glob, shutil

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INBOX = os.path.join(BASE, "inbox")
SIGNALS = os.path.join(BASE, "signals")
OUTBOX = os.path.join(BASE, "outbox")
CLI = "C:/Users/YANGZ/AppData/Roaming/npm/node_modules/@anthropic-ai/claude-code/cli-wrapper.cjs"
A2A = "http://localhost:8765"
HUB = "http://localhost:8767"

os.makedirs(INBOX, exist_ok=True)
os.makedirs(SIGNALS, exist_ok=True)
os.makedirs(OUTBOX, exist_ok=True)


def post(host, path, data):
    req = urllib.request.Request(f"{host}{path}",
        data=json.dumps(data, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json; charset=utf-8"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def run_claude_inspection(task_id, title):
    """Spawn Claude CLI via pipe. Task goes in via stdin, result comes out via stdout."""
    prompt = f"""QualityEvaluator inspection task: {title}

Use Bash to run these one at a time:

1. Read all completed task outputs:
python -c \"import sys; sys.path.insert(0,'.'); import db; [print(t['title'][:60], '|', (t.get('result','') or '')[:200]) for t in db.task_all() if t['status']=='completed']\"

2. Check each output for: API errors, empty outputs, roleplay ('We are X, an AI agent'), thinking>3x content, self-eval templates, repeated outputs.

3. Write report with specific agent names, task titles, and quoted evidence. NOT generic summary.

4. Complete task {task_id}:
python -c \"import urllib.request,json; r=json.loads(urllib.request.urlopen(urllib.request.Request('http://localhost:8765/api/tasks/{task_id}/complete',data=json.dumps({{'agent_id':'QualityEvaluator-f42739','result':'YOUR_REPORT'}}).encode(),headers={{'Content-Type':'application/json'}})).read()); print(r)\"

Be concise. Use real evidence from step 1. Do NOT use templates."""

    cmd = f'node "{CLI}" -p "{prompt}" --dangerously-skip-permissions --output-format text'

    try:
        result = subprocess.run(
            cmd, shell=True, cwd=BASE,
            capture_output=True, text=True, timeout=300,
            encoding='utf-8', errors='replace'
        )
        return result.stdout[:3000] if result.stdout else f"(no output, stderr: {result.stderr[:200]})"
    except subprocess.TimeoutExpired:
        return "(Claude CLI timeout after 120s)"
    except Exception as e:
        return f"(Claude CLI error: {e})"


def main():
    # Check inbox
    files = sorted(glob.glob(os.path.join(INBOX, "*.json")))
    if not files:
        return  # Silent

    print(f"[ClaudeRunner] {len(files)} task(s) found")

    for fpath in files:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                task = json.load(f)
        except Exception:
            continue

        tid = task.get("task_id", "")
        title = task.get("title", "Untitled")
        agent = task.get("agent", "")

        if agent and agent != "QualityEvaluator":
            continue

        print(f"  [{tid[:16]}] {title[:60]}")
        print(f"  Spawning Claude CLI...")

        # Claim + run
        try:
            post(HUB, "/claim", {"task_id": tid, "agent_id": "QualityEvaluator"})
        except Exception:
            pass

        output = run_claude_inspection(tid, title)
        print(f"  Output: {output[:200]}...")

        # Write to outbox
        out_path = os.path.join(OUTBOX, f"{tid}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({"task_id": tid, "title": title, "output": output,
                       "completed_at": time.time()}, f, ensure_ascii=False, indent=2)

        # Clean inbox
        os.remove(fpath)
        print(f"  [DONE]")


if __name__ == "__main__":
    main()
