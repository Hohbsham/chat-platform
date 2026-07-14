"""
One-shot combined watcher + chain — no cron, no lockfile, no separate processes.
Sequentially: QE → Claude → BPTtrain → BPT_Data_Check
Custom wake message per agent.
"""
import os, sys, json, time, ctypes, subprocess

BASE = r"d:\ClothesNetData\chat-platform"
CLI = os.path.join(BASE, "a2a_cli.py")
SIGNALS = os.path.join(BASE, "signals")
os.makedirs(SIGNALS, exist_ok=True)

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

STEPS = [
    {
        "agent": "QualityEvaluator",
        "title": "[周报接力①] QualityEvaluator — 请写你的周报",
        "window_key": "chat-platform",
        "msg": "请填写你的周报第1部分：本周工作、结果数据、遇到的问题、下周计划。完成后提交。只写你自己的部分，不要替别人写。",
    },
    {
        "agent": "Claude",
        "title": "[周报接力②] Claude — 请阅读上文并追加你的周报",
        "window_key": ".claude",
        "msg": "QualityEvaluator已经写了他的周报。请阅读上面的内容，然后追加你自己的周报部分。保留前面内容，不要修改别人的。",
    },
    {
        "agent": "BPTtrain",
        "title": "[周报接力③] BPTtrain — 请追加你的周报",
        "window_key": "garmageset_download",
        "msg": "前面两位已经写了周报。请阅读上面内容，追加你的训练周报。保留所有前面内容。",
    },
    {
        "agent": "BPT_Data_Check",
        "title": "[周报接力④] BPT_Data_Check — 请汇总全部周报",
        "window_key": "服装自适应",
        "msg": "前面三位都写完了。这是最后一步：1.追加你自己的周报 2.汇总所有人的内容成一份完整周报提交。保留所有前面内容。",
    },
]

# ── Win32 helpers ──
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)

def find_vscode(keyword):
    found = []
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n > 0:
                b = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, b, n + 1)
                if keyword in b.value and "Visual Studio Code" in b.value:
                    found.append(hwnd)
                    return False
        return True
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return found[0] if found else None

def force_fg(hwnd):
    if not hwnd: return False
    if user32.IsIconic(hwnd): user32.ShowWindow(hwnd, 9)
    user32.ShowWindow(hwnd, 5)
    cur = kernel32.GetCurrentThreadId()
    tgt = user32.GetWindowThreadProcessId(hwnd, None)
    try:
        user32.AttachThreadInput(cur, tgt, True)
        user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)
    finally:
        user32.AttachThreadInput(cur, tgt, False)
    time.sleep(0.3)
    return True

def type_and_submit(hwnd, text):
    import pyautogui
    if not force_fg(hwnd):
        return False
    console = kernel32.GetConsoleWindow()
    if console: user32.ShowWindow(console, 6)
    try:
        rect = (ctypes.c_int * 4)()
        ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect))
        wx, wy = rect[0], rect[1]
        ww, wh = rect[2] - wx, rect[3] - wy
        if console: user32.ShowWindow(console, 6)
        time.sleep(0.3)
        # Triple click input area
        ix, iy = wx + int(ww * 0.60), wy + int(wh * 0.65)
        pyautogui.click(ix, iy, clicks=3, interval=0.1)
        time.sleep(0.5)
        # Type custom message via clipboard paste (bypasses IME)
        import subprocess
        # Write to clipboard via PowerShell
        ps_cmd = f'Set-Clipboard -Value @\"\n{text}\n\"@'
        subprocess.run(['powershell', '-NoProfile', '-Command', ps_cmd], check=False, timeout=5)
        time.sleep(0.2)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.5)  # Let paste complete
        time.sleep(0.3)
        # Click submit
        sx, sy = wx + int(ww * 0.79), wy + int(wh * 0.70)
        pyautogui.moveTo(sx, sy, duration=0.1)
        pyautogui.mouseDown(sx, sy)
        time.sleep(0.05)
        pyautogui.mouseUp(sx, sy)
        return True
    finally:
        if console: user32.ShowWindow(console, 9)

def run_cli(*args):
    r = subprocess.run([sys.executable, CLI] + list(args), capture_output=True, text=True, timeout=30)
    return r.stdout.strip()

def extract_task_id(s):
    for p in s.split():
        if p.startswith("task-"): return p
    return None

def poll_done(task_id, timeout=1800):
    """Poll every 15s until task completed or timeout."""
    waited = 0
    while waited < timeout:
        out = run_cli("result", task_id)
        if "状态: completed" in out or "状态: failed" in out:
            lines = out.split('\n')
            capture = False
            result = []
            for l in lines:
                if l.startswith("结果:"):
                    capture = True; continue
                if capture: result.append(l)
            return "\n".join(result).strip()
        print(f"  ⏳ {task_id} pending... ({waited}s)", flush=True)
        time.sleep(15)
        waited += 15
    return None

# ── Main ──
print("=" * 60, flush=True)
print("📋 WEEKLY REPORT — FULLY AUTOMATED CHAIN", flush=True)
print("=" * 60, flush=True)

previous_result = None

for i, step in enumerate(STEPS):
    agent = step["agent"]
    print(f"\n{'─'*50}", flush=True)
    print(f"🔵 STEP {i+1}/{len(STEPS)}: {agent}", flush=True)
    
    # 1. Create task
    desc = f"【周报接力 — 第{i+1}棒 — {agent}】\n"
    if previous_result:
        desc += f"前面Agent已完成。请阅读下面内容。\n\n---\n{previous_result}\n---\n\n"
    desc += f"现在轮到你({agent})追加。包含4项：\n1. 本周工作\n2. 结果数据\n3. 遇到的问题\n4. 下周计划"
    if i == len(STEPS) - 1:
        desc += "\n\n你是最后一人！保留所有内容，加上汇总表格后提交完整周报。"

    out = run_cli("create", "--title", step["title"], "--desc", desc,
                  "--caps", "weekly_report", "--priority", "high")
    print(f"  📝 {out}", flush=True)
    task_id = extract_task_id(out)
    if not task_id:
        print(f"  ❌ Failed! No task_id", flush=True)
        sys.exit(1)

    # 2. Write signal (so check_signal.py hook works if needed)
    sig = json.dumps({"title": step["title"][:80], "task_id": task_id, "ts": int(time.time())}, ensure_ascii=False)
    with open(os.path.join(SIGNALS, f"{agent}.json"), "w", encoding="utf-8") as f:
        f.write(sig)

    # 3. Find window and wake
    print(f"  🔍 Finding '{step['window_key']}' window...", flush=True)
    hwnd = find_vscode(step["window_key"])
    if not hwnd:
        print(f"  ❌ Window not found! Signal placed anyway for cron.", flush=True)
        # Still wait - cron watcher might pick it up
    else:
        print(f"  ⌨️  Typing custom message...", flush=True)
        ok = type_and_submit(hwnd, step["msg"])
        print(f"  {'✅' if ok else '❌'} Wake {'successful' if ok else 'failed'}", flush=True)

    # 4. Wait for completion
    print(f"  ⏳ Waiting for {agent} to complete...", flush=True)
    result = poll_done(task_id)
    if result is None:
        print(f"  ❌ TIMEOUT after 30min!", flush=True)
        sys.exit(1)
    print(f"  ✅ {agent} DONE! ({len(result)} chars)", flush=True)
    previous_result = result

    # 5. Clean signal
    sig_path = os.path.join(SIGNALS, f"{agent}.json")
    if os.path.exists(sig_path): os.remove(sig_path)
    time.sleep(3)

print("\n" + "=" * 60, flush=True)
print("✅✅✅ ALL 4 AGENTS COMPLETED WEEKLY REPORT! ✅✅✅", flush=True)
print("=" * 60, flush=True)
