"""
Weekly Report Relay Chain — Fully Automated
QE → Claude → BPTtrain → BPT_Data_Check

Usage:
  python scripts/weekly_report_chain.py              # 从头开始
  python scripts/weekly_report_chain.py --resume 2   # 从第2步(Claude)开始

This script runs autonomously — no human intervention needed.
"""
import os, sys, json, time, glob, subprocess

BASE = r"d:\ClothesNetData\chat-platform"
CLI = os.path.join(BASE, "a2a_cli.py")
SIGNALS = os.path.join(BASE, "signals")

CHAIN = [
    {
        "agent": "QualityEvaluator",
        "title": "[周报接力①] QualityEvaluator — 请写你的周报",
        "desc": "【周报接力 — 第1棒】\n你是 QualityEvaluator，请写你这周的周报，包含4项：\n1. 本周工作\n2. 结果数据\n3. 遇到的问题\n4. 下周计划\n\n⚠️ 只写你自己的部分！不要替其他Agent写！",
    },
    {
        "agent": "Claude",
        "title": "[周报接力②] Claude — 请阅读上文并追加",
        "desc": "【周报接力 — 第2棒】\nQualityEvaluator 已经完成了他的周报。请阅读上面的内容。\n现在轮到你(Claude)追加你的周报部分。4项要求。\n⚠️ 保留前面内容，在后面追加！不要修改别人的！",
    },
    {
        "agent": "BPTtrain",
        "title": "[周报接力③] BPTtrain — 请阅读上文并追加",
        "desc": "【周报接力 — 第3棒】\n前面两位已经完成了他们的周报。请阅读上面的内容。\n现在轮到你(BPTtrain)追加。4项要求。\n⚠️ 保留前面内容，在后面追加！",
    },
    {
        "agent": "BPT_Data_Check",
        "title": "[周报接力④] BPT_Data_Check — 请汇总全部周报",
        "desc": "【周报接力 — 第4棒(汇总)】\n前面三位已经完成了。阅读所有内容。\n1. 追加你自己的周报\n2. 在所有内容最后加上【平台周汇总表】\n⚠️ 保留所有前面内容！",
    },
]


def run_cli(*args):
    cmd = [sys.executable, CLI] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result.stdout.strip()


def clean_signals():
    for f in glob.glob(os.path.join(SIGNALS, "*.json")):
        try: os.remove(f)
        except: pass


def place_signal(agent, task_id, title):
    sig = json.dumps({"title": title[:80], "task_id": task_id, "ts": int(time.time())}, ensure_ascii=False)
    with open(os.path.join(SIGNALS, f"{agent}.json"), "w", encoding="utf-8") as f:
        f.write(sig)
    print(f"[SIGNAL] → {agent}.json (task {task_id})", flush=True)


def poll_until_done(task_id, timeout=900, interval=15):
    """Block until task is completed. Returns result text or None on timeout."""
    elapsed = 0
    while elapsed < timeout:
        out = run_cli("result", task_id)
        if "状态: completed" in out or "状态: failed" in out:
            lines = out.split("\n")
            result_start = False
            result_lines = []
            for line in lines:
                if line.startswith("结果:"):
                    result_start = True
                    continue
                if result_start:
                    result_lines.append(line)
            text = "\n".join(result_lines).strip()
            return text if text else None
        elapsed += 15
        print(f"  [POLL] {task_id} still pending ({elapsed}s)...", flush=True)
        time.sleep(15)
    return None


def create_task(title, desc):
    out = run_cli("create", "--title", title, "--desc", desc, "--caps", "weekly_report", "--priority", "high")
    print(f"[CREATE] {out}", flush=True)
    for part in out.split():
        if part.startswith("task-"):
            return part
    return None


def main():
    # Parse resume point
    resume_from = 0
    if "--resume" in sys.argv:
        idx = sys.argv.index("--resume")
        resume_from = int(sys.argv[idx + 1])

    print("=" * 60, flush=True)
    print(f"📋 Weekly Report Chain (starting step {resume_from + 1})", flush=True)
    print("=" * 60, flush=True)

    # Clean stale signals (to prevent double triggers)
    if resume_from == 0:
        clean_signals()
        print("[CLEAN] Old signals removed", flush=True)

    previous_result = None
    last_task_id = None

    for i, step in enumerate(CHAIN):
        if i < resume_from:
            continue  # Skip already-completed steps

        agent = step["agent"]

        # Build description with previous agent's result
        if previous_result:
            full_desc = step["desc"] + "\n\n---\n## 前面Agent已完成的内容：\n" + previous_result
        else:
            full_desc = step["desc"]

        # Create task
        task_id = create_task(step["title"], full_desc)
        if not task_id:
            print(f"[ERROR] Failed to create task for {agent}", flush=True)
            sys.exit(1)

        # Place single signal
        place_signal(agent, task_id, step["title"])

        # Wait for completion
        print(f"[WAIT] Waiting for {agent} to finish...", flush=True)
        result_text = poll_until_done(task_id)
        if result_text is None:
            print(f"[TIMEOUT] {agent} did not complete!", flush=True)
            sys.exit(1)

        print(f"[DONE] {agent} — {len(result_text)} chars", flush=True)
        previous_result = result_text
        last_task_id = task_id

        # Clean this agent's signal
        sig_path = os.path.join(SIGNALS, f"{agent}.json")
        if os.path.exists(sig_path):
            os.remove(sig_path)

        time.sleep(3)  # Brief pause between steps

    print("\n" + "=" * 60, flush=True)
    print("✅ ALL AGENTS COMPLETED WEEKLY REPORT!", flush=True)
    print(f"   Final task: {last_task_id}", flush=True)
    print("=" * 60, flush=True)


if __name__ == "__main__":
    main()
