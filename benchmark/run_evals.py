"""
Agent Capability Benchmark Harness
Evaluates A2A platform across 10 standardized test scenarios.
Usage: python run_evals.py [--server http://localhost:8765] [--output results.json]
"""
import json, time, sys, os, urllib.request, urllib.error
from pathlib import Path
from datetime import datetime

BENCH_DIR = Path(__file__).parent
TASKS_DIR = BENCH_DIR / "tasks"
HOST = os.environ.get("CHAT_HOST", "http://localhost:8765")

# ── Helpers ────────────────────────────────────────────────────

def api(method, path, data=None):
    url = f"{HOST}{path}"
    body = json.dumps(data).encode("utf-8") if data else None
    headers = {"Content-Type": "application/json"} if body else {}
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": str(e)}

def load_tasks():
    tasks = []
    for f in sorted(TASKS_DIR.glob("*.json")):
        with open(f, "r", encoding="utf-8") as fp:
            tasks.append(json.load(fp))
    return tasks

def check_server():
    try:
        h = api("GET", "/api/health")
        return h.get("ok", False), h
    except Exception as e:
        return False, {"error": str(e)}

# ── Evaluation Logic ───────────────────────────────────────────

def evaluate_task(bench_def):
    """Run a single benchmark task and return results."""
    task_def = bench_def["task"]
    expected = bench_def["expected"]
    result = {
        "bench_id": bench_def["id"],
        "name": bench_def["name"],
        "category": bench_def["category"],
        "weight": bench_def["weight"],
        "passed": False,
        "latency_s": 0,
        "num_responses": 0,
        "errors": [],
        "details": "",
    }

    start = time.time()

    # Create task
    resp = api("POST", "/api/tasks", task_def)
    if not resp.get("ok"):
        if expected.get("expect_validation_error"):
            result["passed"] = True
            result["details"] = "Validation error correctly raised"
            return result
        result["errors"].append(f"Task creation failed: {resp.get('error')}")
        return result

    task_id = resp["task"]["task_id"]
    created_task = resp["task"]

    # Check: should_not_claim (dependency/tool hallucination)
    if expected.get("should_not_claim"):
        # Wait briefly, then verify no agent claimed it
        time.sleep(10)
        t = api("GET", f"/api/tasks/{task_id}")
        if isinstance(t, dict) and t.get("status") == "pending" and not t.get("claimed_by"):
            result["passed"] = True
            result["details"] = "Correctly unclaimed by incapable agents"
        else:
            result["errors"].append(f"Task was claimed despite unmatched capabilities/dependencies")
        result["latency_s"] = round(time.time() - start, 1)
        return result

    # For broadcast tasks: poll for responses
    is_broadcast = created_task.get("broadcast", False)
    max_wait = expected.get("max_latency_s", 60)
    poll_interval = 3
    waited = 0

    while waited < max_wait:
        time.sleep(poll_interval)
        waited += poll_interval
        t = api("GET", f"/api/tasks/{task_id}")
        if isinstance(t, dict):
            responses = t.get("responses", [])
            if is_broadcast:
                if len(responses) >= expected.get("min_responses", 1):
                    break
            else:
                if t.get("status") in ("completed", "failed", "input_required"):
                    break
        else:
            result["errors"].append("Task not found during polling")
            break

    result["latency_s"] = round(time.time() - start, 1)

    # Evaluate results
    final_task = api("GET", f"/api/tasks/{task_id}")
    if isinstance(final_task, dict):
        responses = final_task.get("responses", [])
        result["num_responses"] = len(responses)

        # Check min responses
        if len(responses) < expected.get("min_responses", 1):
            result["errors"].append(f"Only {len(responses)} responses (need {expected['min_responses']})")

        # Check approval flow
        if expected.get("should_request_approval"):
            if final_task.get("status") == "input_required":
                result["passed"] = True
                result["details"] = "HITL approval flow triggered correctly"
            else:
                result["errors"].append(f"Expected input_required, got {final_task.get('status')}")
            return result

        # Check content keywords
        all_text = " ".join([r.get("result", r.get("content", ""))
                            for r in responses if isinstance(r, dict)])
        for kw in expected.get("required_keywords", []):
            if kw.lower() not in all_text.lower():
                result["errors"].append(f"Missing required keyword: {kw}")

        for kw in expected.get("forbidden_keywords", []):
            if kw.lower() in all_text.lower():
                result["errors"].append(f"Found forbidden keyword: {kw}")

    # Pass/fail
    if not result["errors"]:
        result["passed"] = True
        result["details"] = f"Completed in {result['latency_s']}s with {result['num_responses']} responses"
    else:
        result["details"] = "; ".join(result["errors"])

    return result


# ── Report Generation ──────────────────────────────────────────

CATEGORY_COLORS = {
    "basic": "🟢", "context": "🔵", "tool_use": "🟡",
    "dependency": "🟠", "broadcast": "🟣", "groupchat": "🔷",
    "approval": "✋", "concurrency": "⚡", "robustness": "🔴",
}

def print_report(results):
    print()
    print("=" * 85)
    print("  A2A Agent Capability Benchmark — Evaluation Report")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  |  {len(results)} scenarios")
    print("=" * 85)

    # Summary table
    print(f"\n{'':4s}{'Category':14s}{'Scenario':42s}{'Pass':6s}{'Latency':>8s}{'Score':>7s}")
    print("-" * 85)

    passed = 0; total_weight = 0; weighted_score = 0
    errors_by_category = {}

    for r in results:
        cat_icon = CATEGORY_COLORS.get(r["category"], "⚪")
        status = "✅" if r["passed"] else "❌"
        if r["passed"]:
            passed += 1
            weighted_score += r["weight"]
        else:
            for err in r["errors"]:
                cat = r["category"]
                errors_by_category.setdefault(cat, []).append(err)
        total_weight += r["weight"]
        print(f"  {cat_icon} {r['category']:12s} {r['name'][:40]:40s}  {status}   {r['latency_s']:5.1f}s  {r['weight']:4.1f}/{r['weight'] if r['passed'] else 0:.1f}")

    print("-" * 85)

    # Metrics
    success_rate = passed / len(results) * 100
    avg_latency = sum(r["latency_s"] for r in results) / len(results)
    coverage = weighted_score / total_weight * 100 if total_weight > 0 else 0

    print(f"\n  📊 Summary Metrics")
    print(f"  {'─' * 40}")
    print(f"  Pass Rate:       {passed}/{len(results)} ({success_rate:.0f}%)")
    print(f"  Weighted Score:  {weighted_score:.1f}/{total_weight:.1f} ({coverage:.0f}%)")
    print(f"  Avg Latency:     {avg_latency:.1f}s")

    # Error distribution
    if errors_by_category:
        print(f"\n  🔍 Error Distribution by Category")
        for cat, errs in sorted(errors_by_category.items()):
            print(f"  {CATEGORY_COLORS.get(cat,'⚪')} {cat}: {len(errs)} errors")
            for e in errs[:2]:
                print(f"     └ {e[:80]}")

    # Rating
    if success_rate >= 90: rating = "EXCELLENT ⭐⭐⭐"
    elif success_rate >= 70: rating = "GOOD ⭐⭐"
    elif success_rate >= 50: rating = "FAIR ⭐"
    else: rating = "NEEDS WORK"

    print(f"\n  🏆 Overall Rating: {rating}")

    return {
        "timestamp": datetime.now().isoformat(),
        "total_scenarios": len(results),
        "passed": passed,
        "success_rate_pct": round(success_rate, 1),
        "weighted_coverage_pct": round(coverage, 1),
        "avg_latency_s": round(avg_latency, 1),
        "errors_by_category": {k: len(v) for k, v in errors_by_category.items()},
        "rating": rating,
        "scenarios": results,
    }


# ── Main ───────────────────────────────────────────────────────

def main():
    import argparse
    p = argparse.ArgumentParser(description="A2A Agent Capability Benchmark")
    p.add_argument("--server", default=HOST, help="Platform server URL")
    p.add_argument("--output", default=None, help="Save results to JSON file")
    p.add_argument("--category", default=None, help="Run only specific category")
    p.add_argument("--quick", action="store_true", help="Reduce wait times for quick check")
    args = p.parse_args()

    global HOST
    HOST = args.server

    # Health check
    ok, health = check_server()
    if not ok:
        print(f"❌ Server not reachable at {HOST}: {health.get('error','unknown')}")
        print("   Start with: python launcher.py all")
        sys.exit(1)

    online = health.get("agents_online", 0)
    print(f"✅ Server online — {online} agents ready")
    if online < 2:
        print("⚠️  Less than 2 agents online, some benchmarks may fail")

    # Run benchmarks
    all_tasks = load_tasks()
    to_run = [t for t in all_tasks if not args.category or t["category"] == args.category]
    print(f"\nRunning {len(to_run)} benchmark scenarios...\n")

    results = []
    for i, task in enumerate(to_run):
        print(f"  [{i+1}/{len(to_run)}] {task['name']:45s} ... ", end="", flush=True)
        r = evaluate_task(task)
        results.append(r)
        print("✅" if r["passed"] else f"❌ ({len(r['errors'])} errors)")

    # Report
    summary = print_report(results)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print(f"\n📄 Results saved to {args.output}")


if __name__ == "__main__":
    main()
