"""
OS-Level Janitor Trigger — Win32 API window manipulation.
Bypasses VS Code webview sandbox to wake Claude when tasks arrive.

Pipeline:
  Task → signal file written → desktop_watcher detects → wake_vscode.py
    → Find VS Code window → force foreground
    → click tab bar → click Claude panel → type 'look at signals/'
    → click submit (79%,94%)
    → UserPromptSubmit hook → check_signal.py injects task
    → Claude works → completes on A2A
"""
import ctypes
from ctypes import wintypes
import time
import sys
import os
import json

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "agent_windows.json")


def _load_agent_windows():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.loads(f.read())
        return {k: v for k, v in data.items() if not k.startswith("_")}
    return {}


AGENT_WINDOWS = _load_agent_windows()


def find_window(title_fragment):
    """Find a visible VS Code window whose title contains the fragment."""
    found = []

    def enum_callback(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buff, length + 1)
                title = buff.value
                if title_fragment in title and "Visual Studio Code" in title:
                    found.append(hwnd)
                    return False
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
    user32.EnumWindows(WNDENUMPROC(enum_callback), 0)
    return found[0] if found else None


def force_foreground(hwnd):
    """Force window to foreground with AttachThreadInput (bypasses lock)."""
    if not hwnd:
        return False
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)
    user32.ShowWindow(hwnd, 5)
    user32.BringWindowToTop(hwnd)

    current_thread = kernel32.GetCurrentThreadId()
    target_thread = user32.GetWindowThreadProcessId(hwnd, None)
    user32.AttachThreadInput(current_thread, target_thread, True)
    user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)
    user32.AttachThreadInput(current_thread, target_thread, False)

    time.sleep(0.3)
    return True


def click_submit(hwnd):
    """Click Claude Code submit button at calibrated screen position (79%,94%)."""
    import pyautogui
    rect = (ctypes.c_int * 4)()
    ctypes.windll.dwmapi.DwmGetWindowAttribute(
        hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect))
    wx, wy = rect[0], rect[1]
    ww, wh = rect[2] - wx, rect[3] - wy
    cx = wx + int(ww * 0.79)
    cy = wy + int(wh * 0.70)
    pyautogui.click(cx, cy)


def wake_up(agent_name=None):
    """Wake up a specific agent's VS Code window."""
    if not agent_name or agent_name not in AGENT_WINDOWS:
        return False

    fragment = AGENT_WINDOWS[agent_name]
    hwnd = find_window(fragment)
    if not hwnd:
        return False

    if not force_foreground(hwnd):
        return False

    import pyautogui

    # Force foreground and KEEP it — re-force before each operation
    def ensure_foreground():
        for _ in range(5):
            user32.SetForegroundWindow(hwnd)
            user32.BringWindowToTop(hwnd)
            time.sleep(0.2)
            if user32.GetForegroundWindow() == hwnd:
                return True
        return False

    if not ensure_foreground():
        return False

    rect = (ctypes.c_int * 4)()
    ctypes.windll.dwmapi.DwmGetWindowAttribute(
        hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect))
    wx, wy = rect[0], rect[1]
    ww, wh = rect[2] - wx, rect[3] - wy

    # Triple-click Claude input box at (60%, 65%)
    ensure_foreground()
    ix, iy = wx + int(ww * 0.60), wy + int(wh * 0.65)
    pyautogui.click(ix, iy, clicks=3, interval=0.1)
    time.sleep(0.5)

    # Type trigger text
    ensure_foreground()
    pyautogui.write('look at signals/', interval=0.05)
    time.sleep(0.5)

    # Single submit click at (79%, 70%)
    ensure_foreground()
    sx, sy = wx + int(ww * 0.79), wy + int(wh * 0.70)
    pyautogui.moveTo(sx, sy, duration=0.1)
    time.sleep(0.1)
    pyautogui.mouseDown(sx, sy)
    time.sleep(0.05)
    pyautogui.mouseUp(sx, sy)

    # Wait for Claude hook to process
    time.sleep(15)
    return True


if __name__ == "__main__":
    agent = sys.argv[1] if len(sys.argv) > 1 else None
    ok = wake_up(agent)
    sys.exit(0 if ok else 1)
