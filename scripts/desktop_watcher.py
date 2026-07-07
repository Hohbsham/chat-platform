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
    pyautogui.click(wx + int(ww * 0.79), wy + int(wh * 0.94))


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

        # Click editor area for focus (well below menu bar)
        pyautogui.click(wx + int(ww * 0.50), wy + 100)
        time.sleep(0.3)
        # Click Claude panel
        pyautogui.click(wx + int(ww * 0.80), wy + int(wh * 0.50))
        time.sleep(0.5)
        # Type + submit
        pyautogui.write('look at signals/', interval=0.05)
        time.sleep(0.5)
        click_submit(hwnd)
        return True
    finally:
        # Restore console
        if console:
            user32.ShowWindow(console, 9)  # SW_RESTORE


def main():
    config = load_config()
    print(f"[Watcher] Agents: {list(config.keys())}")
    print(f"[Watcher] Watching signals/ ...")

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
            print(f"\n[Watcher] {agent}: {title[:60]}")

            hwnd = find_vscode_window(keyword)
            if hwnd:
                print(f"          Waking {keyword} window...")
                wake_agent(hwnd)
                print(f"          Done.")
            else:
                print(f"          Window '{keyword}' not found — signal stays.")

            # Delete signal (don't loop)
            try:
                os.remove(sig_path)
            except Exception:
                pass

            time.sleep(3)  # Cooldown between signals

        time.sleep(2)


if __name__ == "__main__":
    main()
