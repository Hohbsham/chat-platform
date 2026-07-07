"""
A2A Platform Logger — structured logging with task lifecycle timing.

Usage:
    from logger import a2a_logger as log
    log.task_event(task_id, "created")
    log.task_event(task_id, "claimed", agent="Claude")
    log.task_event(task_id, "completed", agent="Claude", result_len=512)
    log.summary()  # Print success rate, avg times
"""
import logging
import time
import os
import sys
import json
from collections import defaultdict

# ── Log file ──
LOG_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(LOG_DIR, "a2a.log")

# ── Configure standard logging ──
def _setup_logger():
    logger = logging.getLogger("a2a")
    logger.setLevel(logging.DEBUG)

    # File handler — full detail
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-5s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logger.addHandler(fh)

    # Console handler — INFO+
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-5s | %(message)s",
        datefmt="%H:%M:%S"
    ))
    logger.addHandler(ch)

    return logger

# ── Task lifecycle tracker ──
class TaskLifecycleTracker:
    """Tracks every task's state transitions with nanosecond timestamps."""

    def __init__(self):
        self._tasks = {}          # task_id -> {state -> timestamp}
        self._history = []        # list of transition records
        self._current_states = {}  # task_id -> current_state

    def record(self, task_id, state, **meta):
        """Record a state transition for a task."""
        now = time.time()
        if task_id not in self._tasks:
            self._tasks[task_id] = {}
        self._tasks[task_id][state] = now
        prev_state = self._current_states.get(task_id)

        elapsed_ms = None
        if prev_state and prev_state in self._tasks[task_id]:
            elapsed_ms = round((now - self._tasks[task_id][prev_state]) * 1000)

        self._current_states[task_id] = state

        record = {
            "ts": now,
            "task_id": task_id,
            "state": state,
            "prev_state": prev_state,
            "elapsed_ms": elapsed_ms,
            **meta,
        }
        self._history.append(record)

        return elapsed_ms

    def elapsed_since(self, task_id, from_state):
        """Return ms since a given state was entered."""
        if task_id in self._tasks and from_state in self._tasks[task_id]:
            return round((time.time() - self._tasks[task_id][from_state]) * 1000)
        return None

    def summary(self):
        """Return stats: count, success rate, avg times per state."""
        if not self._history:
            return {"total": 0}

        by_state = defaultdict(list)
        for r in self._history:
            if r["elapsed_ms"] is not None:
                by_state[r["state"]].append(r["elapsed_ms"])

        completed = sum(1 for r in self._history if r["state"] == "completed")
        failed = sum(1 for r in self._history if r["state"] == "failed")
        total = len(set(r["task_id"] for r in self._history))

        avg_times = {}
        for state, times in sorted(by_state.items()):
            if times:
                avg_times[f"avg_{state}_ms"] = round(sum(times) / len(times))
                avg_times[f"max_{state}_ms"] = max(times)
                avg_times[f"min_{state}_ms"] = min(times)
                avg_times[f"count_{state}"] = len(times)

        return {
            "total_tasks": total,
            "completed": completed,
            "failed": failed,
            "success_rate_pct": round(completed / total * 100, 1) if total else 0,
            **avg_times,
        }

    def task_timeline(self, task_id):
        """Return full timeline for a single task."""
        return [r for r in self._history if r["task_id"] == task_id]


# ── Singleton ──
_logger = _setup_logger()
tracker = TaskLifecycleTracker()


class A2ALogger:
    """Unified logger + lifecycle tracker for the A2A platform."""

    def info(self, msg, **meta):
        extra = f" | {json.dumps(meta, ensure_ascii=False)}" if meta else ""
        _logger.info(f"{msg}{extra}")

    def debug(self, msg, **meta):
        extra = f" | {json.dumps(meta, ensure_ascii=False)}" if meta else ""
        _logger.debug(f"{msg}{extra}")

    def error(self, msg, **meta):
        extra = f" | {json.dumps(meta, ensure_ascii=False)}" if meta else ""
        _logger.error(f"{msg}{extra}")

    def warning(self, msg, **meta):
        extra = f" | {json.dumps(meta, ensure_ascii=False)}" if meta else ""
        _logger.warning(f"{msg}{extra}")

    def task_event(self, task_id, state, **meta):
        """Record a task state transition with timing."""
        prev = tracker._current_states.get(task_id)
        elapsed = tracker.record(task_id, state, **meta)

        timing = f" ({elapsed}ms)" if elapsed else ""
        agent_str = f" [{meta.get('agent', '')}]" if meta.get("agent") else ""
        prev_str = f"{prev}→" if prev else ""
        self.info(f"Task {task_id[:12]}: {prev_str}{state}{agent_str}{timing}", **meta)

    def task_summary(self):
        """Log a summary of all task metrics."""
        s = tracker.summary()
        self.info(
            f"TASKS: {s.get('total_tasks',0)} total, "
            f"{s.get('completed',0)} done, {s.get('failed',0)} failed, "
            f"{s.get('success_rate_pct',0)}% success"
        )
        for k, v in sorted(s.items()):
            if k.startswith("avg_"):
                self.info(f"  {k}: {v}ms")
        return s

    def health_report(self):
        """Generate a comprehensive health report."""
        s = tracker.summary()
        report = {
            "timestamp": time.time(),
            "metrics": s,
            "active_tasks": {
                tid: state
                for tid, state in tracker._current_states.items()
                if state not in ("completed", "failed", "cancelled")
            },
        }
        self.info(f"HEALTH: {json.dumps(report, ensure_ascii=False)}")
        return report


# ── Module-level instance ──
a2a_logger = A2ALogger()

# ── CLI: standalone health check ──
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="A2A Logger — health check")
    p.add_argument("--summary", action="store_true", help="Print task summary")
    p.add_argument("--tail", type=int, default=0, help="Show last N log lines")
    args = p.parse_args()

    if args.summary:
        a2a_logger.task_summary()
    elif args.tail:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
            for line in lines[-args.tail:]:
                print(line.rstrip())
    else:
        h = a2a_logger.health_report()
        print(json.dumps(h, indent=2, ensure_ascii=False))
