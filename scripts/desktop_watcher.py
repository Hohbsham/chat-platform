"""
Desktop Watcher — runs in user's terminal session.
Watches signals/ directory. When a signal appears, directly wakes the target
VS Code window and triggers Claude — all in one process (no subprocess).

Run once:
  python d:\ClothesNetData\chat-platform\scripts\desktop_watcher.py
"""
import os, sys, time, json, ctypes
import pyautogui

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIGNALS = os.path.join(BASE, "signals")
CONFIG = os.path.join(BASE, "agent_windows.json")

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


def load_config():
    if os.path.exists(CONFIG):
        with open(CONFIG, "r", encoding="utf-8") as f:
            return {k: v for k, v in json.loads(f.read()).items()
                    if not k.startswith("_")}
    return {}


def find_vscode_window(keyword):
    found = []
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            l = user32.GetWindowTextLengthW(hwnd)
            if l > 0:
                b = ctypes.create_unicode_buffer(l + 1)
                user32.GetWindowTextW(hwnd, b, l + 1)
                if keyword in b.value and "Visual Studio Code" in b.value:
                    found.append(hwnd)
                    return False
        return True
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return found[0] if found else None


def force_foreground(hwnd):
    if not hwnd: return False
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)
    user32.ShowWindow(hwnd, 5)
    current = kernel32.GetCurrentThreadId()
    target = user32.GetWindowThreadProcessId(hwnd, None)
    user32.AttachThreadInput(current, target, True)
    user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)
    user32.AttachThreadInput(current, target, False)
    time.sleep(0.3)
    return True


def click_submit(hwnd):
    rect = (ctypes.c_int * 4)()
    ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect))
    wx, wy = rect[0], rect[1]
    ww, wh = rect[2] - wx, rect[3] - wy
    # Single deliberate click — double-click cancels the submit
    sx, sy = wx + int(ww * 0.79), wy + int(wh * 0.70)
    pyautogui.moveTo(sx, sy, duration=0.1)
    time.sleep(0.1)
    pyautogui.mouseDown(sx, sy)
    time.sleep(0.05)
    pyautogui.mouseUp(sx, sy)


def wake_agent(hwnd):
    """Wake up the target VS Code window — all in-process."""
    if not force_foreground(hwnd):
        return False

    # Minimize our own console so it doesn't steal pyautogui focus
    console = kernel32.GetConsoleWindow()
    if console:
        user32.ShowWindow(console, 6)  # SW_MINIMIZE

    try:
        rect = (ctypes.c_int * 4)()
        ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect))
        wx, wy = rect[0], rect[1]
        ww, wh = rect[2] - wx, rect[3] - wy

        # Minimize our console so pyautogui targets VS Code not terminal
        console = kernel32.GetConsoleWindow()
        if console:
            user32.ShowWindow(console, 6)  # SW_MINIMIZE
            time.sleep(0.3)

        # Triple-click Claude input box at (60%, 65%) to ensure focus
        ix, iy = wx + int(ww * 0.60), wy + int(wh * 0.65)
        pyautogui.click(ix, iy, clicks=3, interval=0.1)
        time.sleep(0.5)
        # Type trigger text
        pyautogui.write('look at signals/', interval=0.05)
        time.sleep(0.5)
        # Single submit click at (79%, 70%)
        sx, sy = wx + int(ww * 0.79), wy + int(wh * 0.70)
        pyautogui.moveTo(sx, sy, duration=0.1)
        pyautogui.mouseDown(sx, sy)
        time.sleep(0.05)
        pyautogui.mouseUp(sx, sy)
        return True
    finally:
        # Restore console
        if console:
            user32.ShowWindow(console, 9)  # SW_RESTORE


def main():
    # PID lock — prevent duplicate watchers
    import tempfile
    lockfile = os.path.join(tempfile.gettempdir(), "desktop_watcher.lock")
    if os.path.exists(lockfile):
        try:
            with open(lockfile) as f:
                old_pid = int(f.read().strip())
            import ctypes
            SYNCHRONIZE = 0x100000
            handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, old_pid)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                print(f"[Watcher] Already running (PID {old_pid}). Exiting.")
                sys.exit(0)
        except Exception:
            os.remove(lockfile)
    with open(lockfile, "w") as f:
        f.write(str(os.getpid()))

    config = load_config()
    print(f"[Watcher] Agents: {list(config.keys())}")
    print(f"[Watcher] Watching signals/ ...")

    processed = set()  # Track processed task IDs to prevent re-trigger loops

    while True:
        if not os.path.isdir(SIGNALS):
            time.sleep(2)
            continue

        for agent, keyword in config.items():
            sig_path = os.path.join(SIGNALS, f"{agent}.json")
            if not os.path.exists(sig_path):
                continue

            try:
                with open(sig_path, "r", encoding="utf-8") as f:
                    sig = json.load(f)
            except Exception:
                continue

            tid = sig.get("task_id", "?")
            title = sig.get("title", "?")

            # Skip already-processed signals
            if (agent, tid) in processed:
                continue

            print(f"\n[Watcher] {agent}: {title[:60]}")
            processed.add((agent, tid))  # Mark immediately to prevent loops

            hwnd = find_vscode_window(keyword)
            if not hwnd:
                print(f"          Window '{keyword}' NOT FOUND")
                # Still delete signal to prevent loop — hook won't fire anyway
                try: os.remove(sig_path)
                except: pass
                continue

            print(f"          Waking {keyword} window...")
            wake_agent(hwnd)
            print(f"          Done.")
            # Don't rename/delete — check_signal.py hook needs the signal file to inject task
            time.sleep(3)

        time.sleep(2)


if __name__ == "__main__":
    main()
