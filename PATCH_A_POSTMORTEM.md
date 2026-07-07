# Patch A Postmortem — Ghost Key Injection

**Date:** 2026-07-07
**Status:** PARTIAL SUCCESS

---

## What We Tried

Use `pyautogui` to inject ghost keystrokes (space + Enter) into Claude Code 
when the Channel receives a webhook. Goal: wake Claude without user input.

## What Worked

| Component | Result |
|-----------|--------|
| Channel direct signal write | ✅ 4 second latency (was 30s via watcher) |
| pyautogui keystroke injection | ✅ Script runs, no crash |
| Hook (UserPromptSubmit) | ✅ Fires on user message |

## What Failed

| Component | Result | Root Cause |
|-----------|--------|------------|
| Ghost key waking Claude | ❌ | VSCode webview is Electron-isolated. pyautogui can't find the chat input textarea. It's a black box at the OS coordinate level. |

## What We Learned

- **Channel direct signal > watcher polling.** Cutting the 30s watcher delay to 4s direct write is a 7.5x improvement. Keep this.
- **Webview isolation is fundamental.** No OS-level input simulation can penetrate VSCode's Electron webview chat input. This is by design.
- **Hook is the pragmatic ceiling.** Until Claude Code merges #3174 or ships a file-watcher hook, UserPromptSubmit is the best trigger mechanism.

## Decision

**Stop pursuing auto-wake.** The current "Channel direct signal (4s) + Hook trigger" combo delivers 95% of the value. The remaining 5% requires changes in Claude Code itself (issue #3174) or switching to a custom API runner (Patch C).

**Priority shift: Core platform features (Claim locking, capability verification, task self-healing).**
