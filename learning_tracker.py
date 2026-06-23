"""
Learning Progress Tracker — stores and analyzes study data for the interview prep system.

Usage:
    from learning_tracker import LearningTracker
    lt = LearningTracker()
    lt.record_algorithm("two-sum", "PASS", {"complexity_ok": True, "time_ms": 1200})
    lt.record_model("multi-head-attention", "PASS", {"principles_score": 4})
    lt.record_baguwen("RLHF", 4, {"depth": "good", "gaps": ["PPO details"]})
    lt.summary()  # Generate study report
"""
import json, os, time
from collections import defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE, "learning_data.json")


class LearningTracker:
    def __init__(self):
        self.data = self._load()

    def _load(self):
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return {
            "algorithms": [],
            "models": [],
            "baguwen": [],
            "difficulty": "Easy",
            "weak_points": [],
            "streaks": {"current": 0, "best": 0},
            "started_at": time.time(),
        }

    def _save(self):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    def record_algorithm(self, problem, result, meta):
        """Record algorithm problem result. result: PASS | PASS with note | RETRY"""
        self.data["algorithms"].append({
            "problem": problem, "result": result, "ts": time.time(), **meta,
        })
        self._update_stats("algorithms", result)
        self._save()

    def record_model(self, task, result, meta):
        """Record model hand-writing task result."""
        self.data["models"].append({
            "task": task, "result": result, "ts": time.time(), **meta,
        })
        self._update_stats("models", result)
        self._save()

    def record_baguwen(self, topic, score, meta):
        """Record baguwen interview score (1-5)."""
        self.data["baguwen"].append({
            "topic": topic, "score": score, "ts": time.time(), **meta,
        })
        if score < 3:
            if topic not in self.data["weak_points"]:
                self.data["weak_points"].append(topic)
        self._save()

    def _update_stats(self, category, result):
        """Adjust difficulty and streaks based on results."""
        records = self.data[category]
        if len(records) < 5:
            return
        recent = records[-5:]
        pass_count = sum(1 for r in recent if "PASS" in str(r.get("result", "")))
        pass_rate = pass_count / 5

        # Streak tracking
        if "PASS" in str(result):
            self.data["streaks"]["current"] += 1
            self.data["streaks"]["best"] = max(
                self.data["streaks"]["best"], self.data["streaks"]["current"]
            )
        else:
            self.data["streaks"]["current"] = 0

        # Difficulty adjustment
        levels = ["Easy", "Medium", "Hard"]
        current_idx = levels.index(self.data.get("difficulty", "Easy"))
        if pass_rate >= 0.8 and current_idx < 2:
            self.data["difficulty"] = levels[current_idx + 1]
        elif pass_rate < 0.5 and current_idx > 0:
            self.data["difficulty"] = levels[current_idx - 1]

    def summary(self):
        """Generate daily study report."""
        d = self.data
        algo_total = len(d["algorithms"])
        algo_pass = sum(1 for a in d["algorithms"] if "PASS" in str(a.get("result", "")))
        model_total = len(d["models"])
        model_pass = sum(1 for m in d["models"] if "PASS" in str(m.get("result", "")))
        baguwen_scores = [b["score"] for b in d["baguwen"]]
        avg_score = round(sum(baguwen_scores) / len(baguwen_scores), 1) if baguwen_scores else 0

        today = [r for r in d["algorithms"] + d["models"] if r.get("ts", 0) > time.time() - 86400]
        today_baguwen = [b for b in d["baguwen"] if b.get("ts", 0) > time.time() - 86400]

        return {
            "total": {
                "algorithms": algo_total,
                "algo_pass_rate": f"{round(algo_pass/algo_total*100) if algo_total else 0}%",
                "models": model_total,
                "model_pass_rate": f"{round(model_pass/model_total*100) if model_total else 0}%",
                "baguwen_avg_score": avg_score,
            },
            "today": {
                "algorithms": len([a for a in today if "algo" not in str(a)]),
                "models": len([m for m in today if "model" not in str(m)]),
                "baguwen": len(today_baguwen),
            },
            "difficulty": d.get("difficulty", "Easy"),
            "weak_points": d.get("weak_points", []),
            "streak": f"连续通过{d['streaks']['current']}题（最佳{d['streaks']['best']}题）",
        }

    def today_plan(self):
        """Generate today's study plan based on history and weak points."""
        s = self.summary()
        difficulty = s["difficulty"]
        weak = s["weak_points"] or ["动态规划", "Attention机制"]

        return {
            "difficulty": difficulty,
            "algorithms": f"3道{difficulty}题，重点关注: {', '.join(weak[:2])}",
            "model_handwriting": "1个模型组件（根据薄弱点选）",
            "baguwen": f"2个知识点（优先复习: {weak[0] if weak else 'RLHF'}）",
            "note": "薄弱点会在每日任务中优先安排，直到掌握度>3/5",
        }


# Singleton
tracker = LearningTracker()


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Learning Tracker")
    p.add_argument("--summary", action="store_true")
    p.add_argument("--plan", action="store_true")
    args = p.parse_args()

    if args.summary:
        print(json.dumps(tracker.summary(), indent=2, ensure_ascii=False))
    elif args.plan:
        print(json.dumps(tracker.today_plan(), indent=2, ensure_ascii=False))
    else:
        print(json.dumps(tracker.summary(), indent=2, ensure_ascii=False))
        print()
        print(json.dumps(tracker.today_plan(), indent=2, ensure_ascii=False))
