"""
Quality Evaluation Reports — formatted CLI output and API-ready JSON summaries.

Usage (standalone):
  python eval_reports.py --agent Claude
  python eval_reports.py --domain code_review
  python eval_reports.py --platform
"""
import json, os, sys, urllib.request, urllib.error

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

HOST = os.environ.get("CHAT_HOST", "http://localhost:8765")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _api_get(path):
    url = f"{HOST}{path}"
    resp = urllib.request.urlopen(url, timeout=10)
    return json.loads(resp.read().decode("utf-8"))


def platform_overview():
    """Fetch and format platform-wide quality overview."""
    try:
        data = _api_get("/api/evaluations/summary")
    except Exception as e:
        return {"error": str(e)}
    return data


def agent_quality_report(agent_name):
    """Fetch evaluations for a specific agent and build a quality report."""
    try:
        evals = _api_get(f"/api/evaluations?agent_name={agent_name}&limit=50")
    except Exception as e:
        return {"error": str(e)}

    if not evals:
        return {"agent": agent_name, "evaluations": 0, "avg_score": 0}

    scores = [e.get("scores", {}).get("overall", 0) for e in evals]
    dims = {}
    strengths = []
    weaknesses = []
    suggestions = []
    for e in evals:
        for dname, dscore in e.get("scores", {}).get("dimensions", {}).items():
            dims.setdefault(dname, []).append(dscore)
        strengths.extend(e.get("strengths", [])[:2])
        weaknesses.extend(e.get("weaknesses", [])[:2])
        suggestions.extend(e.get("suggestions", [])[:2])

    avg_dims = {k: round(sum(v)/len(v), 2) for k, v in dims.items()}
    mid = len(scores) // 2
    first = sum(scores[:mid])/mid if mid > 0 else scores[0] if scores else 0
    second = sum(scores[mid:])/(len(scores)-mid) if len(scores)-mid > 0 else first
    trend = "improving" if second > first + 0.1 else "declining" if second < first - 0.1 else "stable"

    return {
        "agent": agent_name,
        "evaluations": len(evals),
        "avg_score": round(sum(scores)/len(scores), 2) if scores else 0,
        "trend": trend,
        "dimensions": avg_dims,
        "top_strengths": list(set(strengths))[:5],
        "top_weaknesses": list(set(weaknesses))[:5],
        "top_suggestions": list(set(suggestions))[:5],
        "recent": [{
            "task": e.get("task_title", "")[:60],
            "score": e.get("scores", {}).get("overall", 0),
            "domain": e.get("domain", ""),
        } for e in evals[-5:]],
    }


def domain_report(domain):
    """Fetch and format quality report for a domain."""
    try:
        evals = _api_get(f"/api/evaluations?domain={domain}&limit=100")
    except Exception as e:
        return {"error": str(e)}

    if not evals:
        return {"domain": domain, "evaluations": 0}

    agents = {}
    for e in evals:
        name = e.get("agent_name", "?")
        agents.setdefault(name, []).append(e.get("scores", {}).get("overall", 0))

    agent_avgs = {}
    for name, scores in agents.items():
        agent_avgs[name] = round(sum(scores)/len(scores), 2)

    all_scores = [e.get("scores", {}).get("overall", 0) for e in evals]

    return {
        "domain": domain,
        "evaluations": len(evals),
        "avg_score": round(sum(all_scores)/len(all_scores), 2) if all_scores else 0,
        "agents": agent_avgs,
    }


# ── CLI formatting ────────────────────────────────────────────────

BAR_WIDTH = 20

def _bar(value, max_val=5.0):
    filled = int(value / max_val * BAR_WIDTH)
    return "█" * filled + "░" * (BAR_WIDTH - filled)


def print_platform_report():
    data = platform_overview()
    if "error" in data:
        print(f"Error: {data['error']}")
        return
    print()
    print("=" * 65)
    print("  PLATFORM QUALITY OVERVIEW")
    print("=" * 65)
    print(f"  Total Evaluations: {data.get('total_evaluations', 0)}")
    print(f"  Platform Avg:      {data.get('platform_avg', 0)}/5.0")
    print()
    print("  By Domain:")
    for domain, info in sorted(data.get("domains", {}).items()):
        avg = info.get("avg", 0)
        print(f"    {domain:<25s} {_bar(avg)} {avg}/5  ({info.get('count',0)} evals)")
    print("=" * 65)


def print_agent_report(agent_name):
    data = agent_quality_report(agent_name)
    if "error" in data:
        print(f"Error: {data['error']}")
        return
    print()
    print("=" * 65)
    print(f"  AGENT QUALITY: {data['agent']}")
    print("=" * 65)
    print(f"  Evaluations: {data['evaluations']}")
    print(f"  Avg Score:   {data['avg_score']}/5.0  |  Trend: {data['trend']}")
    print()
    if data.get("dimensions"):
        print("  Dimension Averages:")
        for dname, dscore in sorted(data["dimensions"].items()):
            print(f"    {dname:<25s} {_bar(dscore)} {dscore}/5")
    if data.get("top_strengths"):
        print(f"\n  Strengths: {', '.join(data['top_strengths'][:3])}")
    if data.get("top_weaknesses"):
        print(f"  Weaknesses: {', '.join(data['top_weaknesses'][:3])}")
    if data.get("top_suggestions"):
        print(f"\n  Suggestions:")
        for s in data["top_suggestions"][:3]:
            print(f"    • {s}")
    if data.get("recent"):
        print("\n  Recent Evaluations:")
        for r in data["recent"]:
            icon = "🟢" if r["score"] >= 4 else "🟡" if r["score"] >= 3 else "🔴"
            print(f"    {icon} [{r['domain']}] {r['task']} — {r['score']}/5")
    print("=" * 65)


def print_domain_report(domain):
    data = domain_report(domain)
    if "error" in data:
        print(f"Error: {data['error']}")
        return
    print()
    print("=" * 65)
    print(f"  DOMAIN QUALITY: {data['domain']}")
    print("=" * 65)
    print(f"  Evaluations: {data['evaluations']}")
    print(f"  Avg Score:   {data['avg_score']}/5.0")
    if data.get("agents"):
        print("\n  Agent Rankings:")
        for name, avg in sorted(data["agents"].items(), key=lambda x: -x[1]):
            print(f"    {name:<25s} {_bar(avg)} {avg}/5")
    print("=" * 65)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Quality Evaluation Reports")
    p.add_argument("--agent", default=None, help="Agent name for quality report")
    p.add_argument("--domain", default=None, help="Domain for quality report")
    p.add_argument("--platform", action="store_true", help="Platform overview")
    args = p.parse_args()

    if args.agent:
        print_agent_report(args.agent)
    elif args.domain:
        print_domain_report(args.domain)
    else:
        print_platform_report()
