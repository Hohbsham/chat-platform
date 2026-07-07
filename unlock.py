"""
Windows File Unlock Tool
========================
Solves the "gateway.lock is held by another instance" problem when the
original process was killed with taskkill but Windows didn't release the lock.

Uses Windows API MoveFileEx with MOVEFILE_DELAY_UNTIL_REBOOT to schedule
deletion on next reboot. Also tries immediate deletion first.

Usage:
  python unlock.py                           # Unlock all known lock files
  python unlock.py --path <file>             # Unlock specific file
  python unlock.py --list                    # List all known lock files
  python unlock.py --method reboot           # Schedule for deletion on reboot
"""
import os, sys, glob, ctypes
from ctypes import wintypes

# Windows API
kernel32 = ctypes.windll.kernel32
MoveFileEx = kernel32.MoveFileExW
MoveFileEx.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
MoveFileEx.restype = wintypes.BOOL

MOVEFILE_REPLACE_EXISTING = 0x1
MOVEFILE_DELAY_UNTIL_REBOOT = 0x4

# Known lock file locations
HERMES_HOME = os.path.expandvars(r"%LOCALAPPDATA%\hermes")
OPENCLAW_HOME = os.path.expanduser(r"~\.openclaw")

KNOWN_LOCKS = [
    os.path.join(HERMES_HOME, "gateway.lock"),
    os.path.join(HERMES_HOME, "kanban.db.init.lock"),
    os.path.join(HERMES_HOME, "cron", ".jobs.lock"),
    os.path.join(HERMES_HOME, "cron", ".tick.lock"),
    os.path.join(HERMES_HOME, "logs", ".__agent.lock"),
    os.path.join(HERMES_HOME, "logs", ".__errors.lock"),
    os.path.join(HERMES_HOME, "logs", ".__gateway.lock"),
]

def schedule_delete_on_reboot(path):
    """Schedule a file for deletion on next system reboot.
    This works even when the file is currently locked."""
    if not os.path.exists(path):
        return True, "already gone"
    result = MoveFileEx(path, None, MOVEFILE_DELAY_UNTIL_REBOOT)
    if result:
        return True, "scheduled for deletion on reboot"
    else:
        error = ctypes.get_last_error()
        return False, f"MoveFileEx failed: error {error}"

def try_delete(path):
    """Try immediate deletion first."""
    try:
        os.unlink(path)
        return True, "deleted"
    except PermissionError:
        return False, "locked"
    except FileNotFoundError:
        return True, "already gone"

def try_rename_away(path):
    """Try to rename the locked file (sometimes works)."""
    try:
        newpath = path + ".old"
        os.rename(path, newpath)
        os.unlink(newpath)
        return True, "renamed and deleted"
    except Exception:
        return False, "rename failed"

def find_lock_files():
    """Find all potential lock files in Hermes and OpenClaw directories."""
    found = []
    # Check known locations
    for p in KNOWN_LOCKS:
        if os.path.exists(p):
            found.append(p)
    # Also scan for any other .lock files
    for base in [HERMES_HOME, OPENCLAW_HOME]:
        if os.path.exists(base):
            for root, dirs, files in os.walk(base):
                for f in files:
                    if f.endswith(".lock"):
                        fp = os.path.join(root, f)
                        if fp not in found:
                            found.append(fp)
    return found

def main():
    import argparse
    p = argparse.ArgumentParser(description="Windows File Unlock Tool")
    p.add_argument("--path", help="Specific file to unlock")
    p.add_argument("--list", action="store_true", help="List known lock files")
    p.add_argument("--method", choices=["auto", "reboot"], default="auto",
                   help="auto=tries all methods, reboot=schedule reboot delete")
    args = p.parse_args()

    if args.list:
        locks = find_lock_files()
        if locks:
            print(f"Found {len(locks)} lock file(s):")
            for l in locks:
                print(f"  {l}")
        else:
            print("No lock files found.")
        return

    targets = [args.path] if args.path else find_lock_files()

    if not targets:
        print("No lock files to unlock. All clear!")
        return

    print(f"Processing {len(targets)} lock file(s)...")
    print()

    for path in targets:
        print(f"  {path}")
        if not os.path.exists(path):
            print(f"    -> Already gone")
            continue

        if args.method == "reboot":
            ok, msg = schedule_delete_on_reboot(path)
            print(f"    -> {msg}")
            continue

        # Auto mode: try immediate deletion, then rename, then reboot schedule
        ok, msg = try_delete(path)
        if ok:
            print(f"    -> {msg}")
            continue

        ok, msg = try_rename_away(path)
        if ok:
            print(f"    -> {msg}")
            continue

        ok, msg = schedule_delete_on_reboot(path)
        status = "REBOOT NEEDED" if ok else "FAILED"
        print(f"    -> [{status}] {msg}")

    print()
    print("Done. If any files need reboot, restart Windows and they'll be gone.")

if __name__ == "__main__":
    main()
