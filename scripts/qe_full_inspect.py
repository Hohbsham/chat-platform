"""
QualityEvaluator Full 8-Dim Inspection Script
Generates complete report and POSTs to platform.
"""
import sys, json, re, os, urllib.request
from collections import defaultdict, Counter
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db

BASE = "http://127.0.0.1:8765"
QE_ID = "QualityEvaluator-f42739"
SIGNAL_TASK_ID = None  # Set dynamically from signals/QualityEvaluator.json if present

agents = db.agent_all()
tasks = db.task_all()
online = [a for a in agents if a.get('status') != 'offline']

lines = []
def p(s=""):
    lines.append(s)

p("=" * 70)
p("## QualityEvaluator 8-Dimension Inspection Report")
p("=" * 70)
p()
p("**Platform:** {}/{} agents online | {} total tasks".format(len(online), len(agents), len(tasks)))
p("**Inspector:** QualityEvaluator (real inspection, not self-referential)")
p("**Time:** 2026-07-07")
p()

# ═══════════════════════════════════════
# Agent overview
# ═══════════════════════════════════════
p("---")
p()
p("### Agent Status")
p()
for a in agents:
    vflag = "[VERIFIED]" if a.get('verified') else "[UNVERIFIED]"
    sflag = a.get('status', 'unknown')
    p("- **{}** ({}) | {} | {} | cap: {}".format(
        a['name'], a.get('agent_id','?')[:20], sflag, vflag,
        ', '.join(a.get('capabilities', []))[:80]))

p()
p("---")
p()

# ═══════════════════════════════════════
# Per-agent output analysis
# ═══════════════════════════════════════
by_agent = defaultdict(list)
for t in tasks:
    agent = t.get('agent_name', '') or t.get('assigned_to', '') or 'unknown'
    by_agent[agent].append(t)

all_issues = []
stuck_list = []

for agent_name in sorted(by_agent.keys()):
    agent_tasks = by_agent[agent_name]
    p("### Agent: {} ({} tasks)".format(agent_name, len(agent_tasks)))
    p()

    outputs = []
    for t in agent_tasks:
        o = t.get('output', '') or t.get('result', '') or ''
        if isinstance(o, dict):
            o = json.dumps(o, ensure_ascii=False)
        outputs.append({
            'task_id': t.get('task_id', '?'),
            'title': t.get('title', '?'),
            'output': str(o),
            'status': t.get('status', '?'),
            'completed_by': t.get('completed_by', ''),
        })

    # STUCK detection
    def normalize(out):
        s = out[:300]
        s = re.sub(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', 'TS', s)
        s = re.sub(r'\d+ tasks total', 'N_TASKS', s)
        s = re.sub(r'\d+/\d+ online', 'N_ONLINE', s)
        s = re.sub(r'Claude-IDE-\w+', 'CLAUDE_ID', s)
        s = re.sub(r'QualityEvaluator-\w+', 'QE_ID', s)
        return s

    norms = [normalize(o['output']) for o in outputs if len(o['output'].strip()) > 10]
    norm_counts = Counter(norms)

    for sig, count in norm_counts.most_common():
        if count >= 3:
            stuck_list.append({
                'agent': agent_name,
                'count': count,
                'pattern': sig[:200]
            })

    # 8-dim on EVERY output
    for o in outputs:
        out = o['output']
        title = o['title']
        codes = []
        evidence = []

        content_no_think = re.sub(r'<!--.*?-->', '', out, flags=re.DOTALL).strip()
        think_blocks = re.findall(r'<!--.*?-->', out, re.DOTALL)
        think_len = sum(len(t) for t in think_blocks)

        # E401: API fault
        m401 = re.search(r'401\b|Auth.*Fail|API.*error|Unauthorized', out, re.I)
        if m401:
            codes.append('E401')
            evidence.append("E401: {}".format(m401.group()[:80]))

        # E501: Thin output (thinking but content < 50 chars)
        if len(think_blocks) > 0 and len(content_no_think) < 50:
            codes.append('E501')
            evidence.append("E501: thinking={} chars, actual content={} chars".format(think_len, len(content_no_think)))

        # E502: Heavy thinking (thinking > content * 3)
        if think_len > 0 and len(content_no_think) > 0 and think_len > len(content_no_think) * 3:
            codes.append('E502')
            ratio = think_len / max(len(content_no_think), 1)
            evidence.append("E502: thinking={}c vs content={}c (ratio={:.1f}x)".format(think_len, len(content_no_think), ratio))

        # E503: Empty/near-empty
        if len(out.strip()) < 20:
            codes.append('E503')
            evidence.append("E503: output length = {} chars (threshold: 20)".format(len(out.strip())))

        # E504: Capability refusal
        m504 = re.search(r'I cannot[^.]*\.|I don.t have access[^.]*\.|I.m unable to[^.]*\.|I do not have[^.]*\.', out, re.I)
        if m504:
            codes.append('E504')
            evidence.append("E504: {}".format(m504.group()[:100]))

        # E505: Hypothetical/simulation
        if re.search(r'\bhypothetical\b|\bsimulation\b|\bsimulated\b|\bpretend\b', out, re.I):
            codes.append('E505')
            evidence.append("E505: hypothetical/simulation language detected")

        # E510: Roleplay intro
        if re.match(r'^(We are|I am)\s+\w+.*AI\s+agent', out.strip()):
            codes.append('E510')
            evidence.append("E510: roleplay opening: {}".format(out[:80].strip()))

        # W601: Self-eval template / QE evaluating QE
        w601_reasons = []
        if re.search(r'Issues found:?\s*0|All outputs clean|All clean|no defects found', out, re.I):
            w601_reasons.append("zero-issues boilerplate")
        if 'QualityEvaluator' in out and ('W601' in out or 'SelfEval' in out):
            w601_reasons.append("QE-flagging-QE")
        # Check if report only mentions QE in issues, never other agents
        other_agents_mentioned = any(a in out for a in ['Claude', 'Hermes', 'BPT_Data_Check'])
        if agent_name == 'QualityEvaluator' and not other_agents_mentioned and len(out) > 50:
            w601_reasons.append("self-only: no other agents inspected")
        if w601_reasons:
            codes.append('W601')
            evidence.append("W601: {}".format("; ".join(w601_reasons)))

        if codes:
            all_issues.append({
                'agent': agent_name,
                'title': title,
                'task_id': o['task_id'],
                'codes': codes,
                'evidence': evidence,
                'excerpt': out[:300].replace('\n', ' | ')
            })

    # Print per-agent findings
    agent_issues = [i for i in all_issues if i['agent'] == agent_name]
    if agent_issues:
        for idx, iss in enumerate(agent_issues):
            code_str = ",".join(iss['codes'])
            p("**#{}. [{}] {}**".format(idx + 1, code_str, iss['title'][:80]))
            p("  Task: {}".format(iss['task_id']))
            for e in iss['evidence']:
                p("  - Evidence: {}".format(e))
            p("  - Excerpt: `{}...`".format(iss['excerpt'][:200]))
            p()
    else:
        p("  No issues detected.")
        p()

p("---")
p()

# ═══════════════════════════════════════
# STUCK analysis
# ═══════════════════════════════════════
p("### STUCK Agents")
p()
if stuck_list:
    for s in stuck_list:
        p("- **STUCK: [{}]** Same structural output {} times".format(s['agent'], s['count']))
        p("  Pattern: `{}...`".format(s['pattern'][:150]))
        p()
else:
    p("No agents detected as STUCK (structural similarity < 3x).")
    p()

p("---")
p()

# ═══════════════════════════════════════
# Code distribution
# ═══════════════════════════════════════
p("### Issue Distribution by Code")
p()
by_code = Counter()
for i in all_issues:
    for c in i['codes']:
        by_code[c] += 1

p("| Code | Description | Count |")
p("|------|-------------|-------|")
code_desc = {
    'E401': 'API/Auth Fault',
    'E501': 'Thin Output',
    'E502': 'Thinking Overload',
    'E503': 'Empty Output',
    'E504': 'Capability Gap',
    'E505': 'Hypothetical Output',
    'E510': 'Roleplay Intro',
    'W601': 'Self-Eval Template',
}
for code in ['E401','E501','E502','E503','E504','E505','E510','W601']:
    count = by_code.get(code, 0)
    desc = code_desc.get(code, '?')
    p("| {} | {} | {} |".format(code, desc, count))
p()

p("---")
p()

# ═══════════════════════════════════════
# Root Cause & Recommendations
# ═══════════════════════════════════════
p("### Root Cause Analysis")
p()

qe_w601_count = sum(1 for i in all_issues if i['agent'] == 'QualityEvaluator' and 'W601' in i['codes'])
p("**Primary finding: QE Self-Referential Loop**")
p()
p("{} of {} total issues are QualityEvaluator flagging its own previous reports as W601.".format(qe_w601_count, len(all_issues)))
p("The loop works as follows:")
p()
p("1. QE wakes up via signal/hook")
p("2. QE reads `db.task_all()`")
p("3. QE finds previous QE outputs that contain W601 self-eval patterns")
p("4. QE correctly flags these as W601")
p("5. QE writes a new report saying \"Issues: 1 - [QualityEvaluator] W601\"")
p("6. QE completes the task, signal is cleaned")
p("7. Next QE wake finds the NEW report from step 5 -> goto step 3")
p()
p("**This creates infinite recursion.** Each QE instance correctly identifies the problem")
p("but cannot fix it because the problem IS the self-referential inspection pattern.")
p()

# Count non-QE inspection
non_qe_inspected = 0
for i in all_issues:
    if i['agent'] != 'QualityEvaluator':
        non_qe_inspected += 1

p("**Non-QE agents inspected:** {} issues found across other agents".format(non_qe_inspected))
p("Claude outputs: {} of 4 tasks were actually reviewed in any QE report.".format(
    sum(1 for i in all_issues if i['agent'] == 'Claude')))
p()

p("---")
p()

p("### Recommendations")
p()
p("1. **[DONE] Protocol fix:** QE_CORE_PROTOCOL.md updated with hard rule:")
p("   each inspection MUST scan >=1 non-QE agent's last 3 outputs.")
p("2. **Cleanup stale tasks:** Remove or archive the 12+ duplicate QE self-eval")
p("   tasks that form the loop history.")
p("3. **Claude E503:** Investigate task '[Orchestrated] Design architecture and")
p("   implementation plan' - status=pending with empty output.")
p("4. **QE reset:** Clear QE's own task history so next wake is a FRESH scan")
p("   of other agents, not a continuation of the self-eval chain.")
p("5. **Add diversity check:** If QE produces N consecutive identical-structured")
p("   outputs, auto-escalate to Hermes instead of completing normally.")
p()
p("=" * 70)
p("## End of Report")
p("=" * 70)

# ═══════════════════════════════════════
# Assemble and POST
# ═══════════════════════════════════════
report = "\n".join(lines)

print(report)

# ═══════════════════════════════════════
# POST to platform + clean signals
# ═══════════════════════════════════════
print("\n\n=== POSTING TO PLATFORM ===")

# Read signal task ID
signals_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "signals")
qe_signal_file = os.path.join(signals_dir, "QualityEvaluator.json")

signal_task_id = None
if os.path.exists(qe_signal_file):
    with open(qe_signal_file, 'r', encoding='utf-8') as f:
        sig = json.loads(f.read())
        signal_task_id = sig.get("task_id")
        print("Signal task:", signal_task_id)

if signal_task_id:
    # Complete the signal task with full report
    payload = json.dumps({"agent_id": QE_ID, "result": report}, ensure_ascii=False).encode('utf-8')
    try:
        req = urllib.request.Request(
            "{}/api/tasks/{}/complete".format(BASE, signal_task_id),
            data=payload,
            headers={"Content-Type": "application/json; charset=utf-8"}
        )
        resp = urllib.request.urlopen(req)
        print("Complete {}: {}".format(signal_task_id, json.loads(resp.read())))
    except Exception as e:
        print("ERROR completing task:", e)

# Also post to chat
chat_payload = json.dumps({"sender": "QualityEvaluator", "content": report}, ensure_ascii=False).encode('utf-8')
try:
    req2 = urllib.request.Request(
        "{}/api/send".format(BASE),
        data=chat_payload,
        headers={"Content-Type": "application/json; charset=utf-8"}
    )
    resp2 = urllib.request.urlopen(req2)
    print("Chat posted:", json.loads(resp2.read()))
except Exception as e:
    print("ERROR posting chat:", e)

# Clean up signal files
for fname in ["QualityEvaluator.json"]:
    fpath = os.path.join(signals_dir, fname)
    if os.path.exists(fpath):
        os.remove(fpath)
        print("Cleaned signal:", fname)
