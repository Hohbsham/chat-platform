"""
Desktop Watcher — the missing link between signals and window wake-up.

Polls signals/ for new task signals. For each one, runs wake_vscode.py to
pull that agent's VS Code window to the front and inject the task.

Must run in a REAL terminal session (not a detached process) — pyautogui
needs desktop focus to move the mouse.

Usage:
  python scripts/desktop_watcher.py              # 3s poll
  python scripts/desktop_watcher.py --interval 5
  python scripts/desktop_watcher.py --dry-run    # log only, no mouse

Why sequential: wake_vscode.py takes over the mouse and keyboard. Two
concurrent wake-ups would fight over focus and type into the wrong window.
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIGNALS_DIR = os.path.join(BASE, "signals")
WAKE_SCRIPT = os.path.join(BASE, "scripts", "wake_vscode.py")
WINDOWS_CFG = os.path.join(BASE, "agent_windows.json")

# A signal older than this is stale — the agent already saw it or gave up.
SIGNAL_TTL = 3600
# Don't re-wake the same agent within this window, even if the signal lingers.
REWAKE_COOLDOWN = 120


def load_known_agents():
    """Agents that have a window mapping — only these can be woken."""
    try:
        with open(WINDOWS_CFG, encoding="utf-8") as f:
            cfg = json.load(f)
        return {k for k in cfg if not k.startswith("_")}
    except Exception:
        return set()


def read_signal(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def wake(agent, dry_run=False):
    """Run wake_vscode.py for one agent. Blocks until done (~20s)."""
    if dry_run:
        print(f"    [dry-run] would wake {agent}")
        return True
    try:
        r = subprocess.run(
            [sys.executable, WAKE_SCRIPT, agent],
            cwd=BASE, capture_output=True, timeout=90, text=True,
        )
        if r.returncode != 0:
            err = (r.stderr or r.stdout or "").strip()[:200]
            print(f"    [fail] {agent} (exit {r.returncode}) {err}")
            return False
        return True
    except subprocess.TimeoutExpired:
        print(f"    [timeout] {agent} — wake took >90s")
        return False
    except Exception as e:
        print(f"    [error] {agent}: {e}")
        return False


def main():
    ap = argparse.ArgumentParser(description="A2A desktop watcher")
    ap.add_argument("--interval", type=float, default=3.0,
                    help="seconds between polls (default 3)")
    ap.add_argument("--dry-run", action="store_true",
                    help="log what would happen, don't touch the mouse")
    args = ap.parse_args()

    known = load_known_agents()
    print("=" * 56)
    print("  A2A Desktop Watcher")
    print(f"  signals: {SIGNALS_DIR}")
    print(f"  agents:  {', '.join(sorted(known)) or '(none configured)'}")
    print(f"  poll:    {args.interval}s" + ("  [DRY RUN]" if args.dry_run else ""))
    print("=" * 56)
    print()

    last_wake = {}  # agent -> timestamp of last wake attempt

    while True:
        try:
            # Reload the window map each cycle so newly registered agents
            # are picked up without a restart.
            known = load_known_agents() or known
            now = time.time()

            for path in sorted(glob.glob(os.path.join(SIGNALS_DIR, "*.json"))):
                name = os.path.basename(path)
                if name.startswith("."):
                    continue  # .chain_state.json and friends
                agent = name[:-5]  # strip .json

                if agent not in known:
                    continue

                sig = read_signal(path)
                if not sig:
                    continue

                age = now - sig.get("ts", 0)
                if age > SIGNAL_TTL:
                    continue

                # The hook writes {agent}.json.injected once Claude has seen
                # the task. If that marker is newer than the signal, we're done.
                injected = path + ".injected"
                if os.path.exists(injected):
                    try:
                        if os.path.getmtime(injected) >= os.path.getmtime(path):
                            continue
                    except OSError:
                        pass

                if now - last_wake.get(agent, 0) < REWAKE_COOLDOWN:
                    continue

                title = (sig.get("title") or "")[:60]
                print(f"[{time.strftime('%H:%M:%S')}] signal: {agent}")
                print(f"    task: {title}")
                last_wake[agent] = now
                if wake(agent, args.dry_run):
                    print(f"    [ok] {agent} woken")
                print()

        except KeyboardInterrupt:
            print("\n[watcher] stopped")
            return
        except Exception as e:
            print(f"[watcher] cycle error: {e}")

        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n[watcher] stopped")
            return


if __name__ == "__main__":
    main()
