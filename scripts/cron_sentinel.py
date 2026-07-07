"""
Cron Sentinel — Guard Filter for Scheme B.

Called by cron/Task Scheduler every 1-5 minutes.
Checks for signal files. If none: exits in <10ms, 0 tokens, Claude never wakes.
If signal found: runs qe_inspect.py (mechanical 8-dim, 0 tokens), then
optionally triggers Claude CLI for real judgment on suspicious outputs.

Architecture:
  Cron → sentinel.py (10ms, 0 token) → signal? → qe_inspect.py (0 token)
                                            ↓ clean but suspicious?
                                         Claude CLI (real judgment)

No persistent process. No polling. No token waste when idle.
"""
import os, sys, json, time, subprocess, glob, urllib.request

BASE = r"d:\ClothesNetData\chat-platform"
SIGNALS = os.path.join(BASE, "signals")
QE_AGENT_ID = "QualityEvaluator-f42739"
A2A = "http://localhost:8765"


def _complete_task(tid, report):
    """POST completion to A2A."""
    req = urllib.request.Request(
        f"{A2A}/api/tasks/{tid}/complete",
        data=json.dumps({
            "agent_id": QE_AGENT_ID,
            "result": report,
        }, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    urllib.request.urlopen(req, timeout=15)


def _run_claude_inspection(tid, title):
    """Escalate to Claude CLI for real AI judgment. Costs tokens — only when needed."""
    CLI = os.path.join(os.environ.get("APPDATA", ""),
                       "npm", "node_modules", "@anthropic-ai", "claude-code", "cli-wrapper.cjs")
    if not os.path.exists(CLI):
        return None

    prompt = f"""Run a real quality inspection on task {tid}: "{title}"

Run this ONCE and report what you find:
  python -c "import sys; sys.path.insert(0,'.'); import db; [print(t['title'][:60],'|',(t.get('result','') or '')[:200]) for t in db.task_all() if t['status']=='completed']"

Check each output for: E401 API failures, E501 thin output, E503 empty, E510 roleplay, W601 self-eval templates, STUCK repeated outputs.

If you find issues, list them with agent name and evidence. If all clean, say so.
DO NOT use template language. Be specific. Be brief."""

    try:
        result = subprocess.run(
            f'node "{CLI}" -p "{prompt}" --dangerously-skip-permissions --output-format text',
            shell=True, cwd=BASE,
            capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace"
        )
        return result.stdout[:2000] if result.stdout else None
    except Exception:
        return None


def main():
    """Stage 0-4 pipeline. Called by cron."""
    # ── Stage 0: Guard check. No signals = silent exit ──
    if not os.path.isdir(SIGNALS):
        sys.exit(0)

    # Only real agent signals (*.json, not .dotfiles)
    signal_files = sorted(glob.glob(os.path.join(SIGNALS, "*.json")))
    signal_files = [s for s in signal_files if not os.path.basename(s).startswith(".")]

    if not signal_files:
        sys.exit(0)  # <10ms. 0 tokens. Silent.

    # ── Stage 1: Signal found → run mechanical 8-dim inspection ──
    now = time.time()
    inspector = os.path.join(BASE, "scripts", "qe_inspect.py")

    for sig_path in signal_files:
        fname = os.path.basename(sig_path)
        agent = fname.replace(".json", "")

        try:
            with open(sig_path, "r", encoding="utf-8") as f:
                sig = json.load(f)
        except Exception:
            os.remove(sig_path)
            continue

        tid = sig.get("task_id", "")
        title = sig.get("title", "Untitled")
        sig_age = now - sig.get("ts", 0)

        # Skip stale signals (>1 hour)
        if sig_age > 3600:
            os.remove(sig_path)
            print(f"[Sentinel] Discarded stale signal: {fname} ({sig_age:.0f}s old)")
            continue

        print(f"[Sentinel] Signal: {agent} → {title[:60]}")

        # Run mechanical inspection first (0 tokens)
        try:
            result = subprocess.run(
                [sys.executable, inspector],
                cwd=BASE,
                capture_output=True, text=True, timeout=60,
                encoding="utf-8", errors="replace"
            )
            report = result.stdout.strip()
        except subprocess.TimeoutExpired:
            report = "(Inspection timeout)"
        except Exception as e:
            report = f"(Inspection error: {e})"

        if not report:
            report = "(Inspection produced no output)"

        # ── Stage 2: Escalate to Claude CLI only if mechanical is clean ──
        needs_claude = ("All clean" in report or "Issues: 0" in report or "Issues found: 0" in report)

        if needs_claude:
            print(f"  Mechanical: clean → triggering Claude CLI for real judgment...")
            cli_report = _run_claude_inspection(tid, title)
            if cli_report and "error" not in cli_report.lower():
                report = cli_report
            else:
                print(f"  CLI unavailable, using mechanical report")

        # ── Stage 3: Complete task on A2A ──
        try:
            _complete_task(tid, report)
            print(f"  [{tid[:16]}] Completed: {report[:80].split(chr(10))[0]}")
        except Exception as e:
            print(f"  [{tid[:16]}] Complete failed: {e}")
            continue

        # ── Stage 4: Consume signal, write log ──
        os.remove(sig_path)
        with open(os.path.join(SIGNALS, ".last_inspection.txt"), "w", encoding="utf-8") as f:
            f.write(report)
        print(f"  [DONE]")


if __name__ == "__main__":
    main()
