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


def focus_claude_input():
    """Focus the Claude Code input box via the Command Palette.

    Percentage-based clicks break whenever the layout shifts (terminal panel
    open, sidebar width, panel docked to a different edge). The palette
    command 'Claude Code: Focus input' resolves the input box regardless of
    where it is on screen, so no coordinates are involved.
    """
    import pyautogui
    # Close any stray palette/quick-pick first so we start from a known state.
    pyautogui.press("escape")
    time.sleep(0.2)
    pyautogui.hotkey("ctrl", "shift", "p")
    time.sleep(0.7)
    # Palette prefills '>'; typing the title filters to the focus command.
    pyautogui.write("Claude Code: Focus input", interval=0.02)
    time.sleep(0.9)
    pyautogui.press("enter")
    time.sleep(0.8)


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

    # Force foreground — hide ALL console windows first, then activate target
    CONSOLE_CLASS = "ConsoleWindowClass"
    def _hide_cb(h, _):
        if user32.IsWindowVisible(h):
            buf = ctypes.create_unicode_buffer(32)
            user32.GetClassNameW(h, buf, 32)
            if buf.value == CONSOLE_CLASS:
                user32.ShowWindow(h, 0)
        return True
    HIDE_ALL = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)(_hide_cb)

    def ensure_foreground():
        for _ in range(5):
            user32.EnumWindows(HIDE_ALL, 0)
            time.sleep(0.15)
            user32.SetForegroundWindow(hwnd)
            user32.BringWindowToTop(hwnd)
            time.sleep(0.2)
            if user32.GetForegroundWindow() == hwnd:
                return True
        return False

    if not ensure_foreground():
        return False

    # Read signal to check if we need to switch models
    import glob
    SIGDIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "signals")
    sig_files = glob.glob(os.path.join(SIGDIR, f"{agent_name}_*.json")) + [os.path.join(SIGDIR, f"{agent_name}.json")]
    sig_path = sig_files[0] if sig_files else ""
    model_cmd = None
    if sig_path and os.path.exists(sig_path):
        try:
            with open(sig_path, "r", encoding="utf-8") as f:
                sig = json.loads(f.read())
            model_cmd = sig.get("model_cmd")
        except Exception:
            pass

    # Switch Sogou IME to English mode (Shift toggles CN→EN)
    ensure_foreground()
    pyautogui.press('shift')
    time.sleep(0.15)

    # Focus the input box by command, not by coordinates
    ensure_foreground()
    focus_claude_input()

    # Clear whatever was already in the box, then type the trigger
    ensure_foreground()
    pyautogui.hotkey('ctrl', 'a')
    time.sleep(0.15)
    pyautogui.write('look at signals/', interval=0.05)
    time.sleep(0.5)

    # Submit with Enter — the send button moves, Enter does not
    ensure_foreground()
    pyautogui.press('enter')

    # Wait for Claude hook to process
    time.sleep(15)
    return True


if __name__ == "__main__":
    agent = sys.argv[1] if len(sys.argv) > 1 else None
    ok = wake_up(agent)
    sys.exit(0 if ok else 1)
