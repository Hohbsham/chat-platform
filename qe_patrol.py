"""
QualityEvaluator Patrol Script — runs one inspection cycle.
Designed to be called repeatedly (cron / schedule).
Claims tasks assigned to QualityEvaluator, evaluates, auto-fixes, reports.
"""
import sys, io, json, time, urllib.request, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8') if hasattr(sys.stdout, 'buffer') else sys.stdout

import db
from quality_evaluator_agent import real_inspect_platform, _run_remediation_loop
from status_codes import build_status_report

HOST = os.environ.get("CHAT_HOST", "http://localhost:8765")


def api_post(path, data):
    body = json.dumps(data, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(HOST + path, data=body,
        headers={'Content-Type': 'application/json; charset=utf-8'})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=30).read())
    except Exception as e:
        return {"ok": False, "error": str(e)}


def api_get(path):
    try:
        return json.loads(urllib.request.urlopen(HOST + path, timeout=10).read())
    except Exception:
        return []


# ── Find our agent ID ──
agents = api_get('/api/agents')
me = next((a for a in agents if a.get('name') == 'QualityEvaluator' and a.get('source') == 'quality_evaluator_agent'), None)
if not me:
    me = next((a for a in agents if a.get('name') == 'QualityEvaluator'), None)
if not me:
    print("[QE] Not registered. Run quality_evaluator_agent.py first.")
    sys.exit(1)

agent_id = me['agent_id']
caps = me.get('capabilities', ['quality_evaluation', 'database_access', 'real_inspection', 'scoring', 'issue_detection'])

# ── Heartbeat ──
api_post('/api/agents/heartbeat', {'agent_id': agent_id})

# ── Try to claim a task ──
result = api_post('/api/tasks/auto-claim', {
    'agent_id': agent_id,
    'capabilities': caps,
})

if result.get('claimed'):
    task = result['claimed']
    tid = task['task_id']
    title = task.get('title', tid)
    print(f"\n[QE] Claimed: {title[:60]}")

    # Run inspection
    report = real_inspect_platform()
    status = build_status_report(report['evaluations'])

    # Run auto-remediation
    remediator = _run_remediation_loop(report, task)
    rem = remediator.summary()

    # Build report
    lines = [
        f"## QE Patrol Report",
        f"**Time:** {time.strftime('%H:%M:%S')} | **Platform:** {status['platform_status']}",
        f"",
        f"### Evaluations ({len(report['evaluations'])} tasks)",
    ]
    for ev in report['evaluations']:
        codes = ','.join(c['code'] for c in ev.get('status_codes', [])) or 'PASS'
        lines.append(f"- [{ev['verdict']}] {ev['agent']}: {ev['score']}/5 [{codes}]")

    lines.append(f"")
    lines.append(f"### Auto-Fix: {rem['fixed']}/{rem['attempted']} resolved")

    if status['blocked_agents']:
        lines.append(f"### BLOCKED: {', '.join(status['blocked_agents'])}")

    result_text = '\n'.join(lines)

    # Complete task
    api_post(f'/api/tasks/{tid}/complete', {
        'agent_id': agent_id,
        'result': result_text,
    })

    # Post to chat
    chat_lines = [f"[QE Patrol] Scanned {len(report['evaluations'])} tasks | "
                  f"Platform: {status['platform_status']} | Fixed: {rem['fixed']}/{rem['attempted']}"]
    if status['blocked_agents']:
        chat_lines.append(f"Blocked: {', '.join(status['blocked_agents'])}")
    if rem['fixed'] > 0:
        for r in remediator.log:
            if r.get('success'):
                chat_lines.append(f"[FIXED] {r['tag']}")

    api_post('/api/send', {'sender': 'QualityEvaluator', 'content': '\n'.join(chat_lines)})

    print(f"[QE] Done. {len(report['evaluations'])} evals, {rem['fixed']} fixes.\n")
else:
    print(f"[QE] {time.strftime('%H:%M:%S')} — No tasks for me. Idle.")

# ── Clear signal file after patrol ──
sig_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "signals", "QualityEvaluator.json")
if os.path.exists(sig_path):
    os.remove(sig_path)


# ── Also check for orphaned tasks ──
all_tasks = db.task_all()
orphaned = [t for t in all_tasks if t.get('status') == 'claimed']
if orphaned:
    api_post('/api/send', {
        'sender': 'QualityEvaluator',
        'content': f"[QE] Found {len(orphaned)} orphaned tasks. Auto-reassigning..."
    })
    for t in orphaned:
        db.task_update(t['task_id'], status='pending', claimed_by=None, claimed_at=None)
    print(f"[QE] Reassigned {len(orphaned)} orphaned tasks.")
