"""
Ghost Key Injector — wakes Claude Code by simulating user input.

When called: types a single space + Enter in the active window.
This triggers UserPromptSubmit Hook → check_signal.py → work found → Claude acts.

Only fires if signal file actually exists (safety check).
"""
import os, json, time, sys

SIGNAL_FILE = r"d:\ClothesNetData\chat-platform\signals\QualityEvaluator.json"

def inject():
    """Simulate a silent keystroke to wake Claude Code."""
    # Safety: only inject if there's actually a signal waiting
    if not os.path.exists(SIGNAL_FILE):
        return

    try:
        import pyautogui
        # Brief pause to avoid interfering with user's active typing
        time.sleep(0.5)

        # Type a single space + Enter → triggers UserPromptSubmit Hook
        # The space is invisible (whitespace), Enter submits it
        pyautogui.typewrite(" ")
        pyautogui.press("enter")

        # Log the injection
        sig_dir = os.path.dirname(SIGNAL_FILE)
        log_path = os.path.join(sig_dir, ".ghost_key_log.txt")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} Ghost key injected — signal existed\n")
    except Exception as e:
        # pyautogui might fail if screen is locked or VSCode not focused
        pass


if __name__ == "__main__":
    inject()
