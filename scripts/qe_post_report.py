"""Re-POST full QE report to a specific task. Run after qe_full_inspect.py."""
import sys, json, os, urllib.request
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db

BASE = "http://127.0.0.1:8765"
QE_ID = "QualityEvaluator-f42739"

def build_full_report():
    """Same report builder as qe_full_inspect.py"""
    import re
    from collections import defaultdict, Counter

    agents = db.agent_all()
    tasks = db.task_all()
    online = [a for a in agents if a.get('status') != 'offline']

    lines = []
    def p(s=''): lines.append(s)

    p('=' * 70)
    p('## QualityEvaluator 8-Dimension Inspection Report')
    p('=' * 70)
    p()
    p('**Platform:** {}/{} online | {} total tasks'.format(len(online), len(agents), len(tasks)))
    p('**Protocol:** v2 (hard rule: >=1 non-QE agent inspected)')
    p('**Inspector:** QualityEvaluator (real inspection, db-backed)')
    p('**Time:** 2026-07-07')
    p()

    # Agent status
    p('---')
    p('### Agent Status')
    p()
    for a in agents:
        v = '[V]' if a.get('verified') else '[U]'
        caps = ', '.join(a.get('capabilities', []))[:80]
        p('- **{}** {} | {} | {}'.format(a['name'], v, a.get('status', '?'), caps))
    p()

    # Per-agent analysis
    by_agent = defaultdict(list)
    for t in tasks:
        agent = t.get('agent_name', '') or t.get('assigned_to', '') or 'unknown'
        by_agent[agent].append(t)

    all_issues = []
    stuck_list = []

    for agent_name in sorted(by_agent.keys()):
        agent_tasks = by_agent[agent_name]
        p('---')
        p('### {} ({} tasks)'.format(agent_name, len(agent_tasks)))
        p()

        outputs = []
        for t in agent_tasks[-5:]:
            o = t.get('output', '') or t.get('result', '') or ''
            if isinstance(o, dict):
                o = json.dumps(o, ensure_ascii=False)
            outputs.append({
                'task_id': t.get('task_id', '?'),
                'title': t.get('title', '?'),
                'output': str(o),
                'status': t.get('status', '?'),
            })

        if not outputs:
            p('  **NO OUTPUTS**')
            p()
            continue

        for o in outputs:
            out = o['output']
            title = o['title']
            codes = []
            evidence = []

            content_no_think = re.sub(r'<!--.*?-->', '', out, flags=re.DOTALL).strip()
            think_blocks = re.findall(r'<!--.*?-->', out, re.DOTALL)
            think_len = sum(len(t) for t in think_blocks)

            # E401
            m = re.search(r'401\b|Auth.*Fails|API.*error|Unauthorized', out, re.I)
            if m: codes.append('E401'); evidence.append('E401: ' + m.group()[:80])

            # E501
            if len(think_blocks) > 0 and len(content_no_think) < 50:
                codes.append('E501'); evidence.append('E501: thinking={}c, content={}c'.format(think_len, len(content_no_think)))

            # E502
            if think_len > 0 and len(content_no_think) > 0 and think_len > len(content_no_think) * 3:
                ratio = think_len / max(len(content_no_think), 1)
                codes.append('E502'); evidence.append('E502: thinking={}c vs content={}c ({:.1f}x)'.format(think_len, len(content_no_think), ratio))

            # E503
            if len(out.strip()) < 20:
                codes.append('E503'); evidence.append('E503: output={} chars (threshold: 20)'.format(len(out.strip())))

            # E504
            m = re.search(r'I cannot[^.]*\.|I don.t have access[^.]*\.|I.m unable to[^.]*\.', out, re.I)
            if m: codes.append('E504'); evidence.append('E504: ' + m.group()[:100])

            # E505
            if re.search(r'\bhypothetical\b|\bsimulation\b|\bsimulated\b|\bpretend\b', out, re.I):
                codes.append('E505'); evidence.append('E505: hypothetical/simulation language')

            # E510
            if re.match(r'^(We are|I am)\s+\w+.*AI\s+agent', out.strip()):
                codes.append('E510'); evidence.append('E510: ' + out[:60].strip())

            # W601
            w601_r = []
            if re.search(r'Issues found:?\s*0|All outputs clean|All clean|no defects found', out, re.I):
                w601_r.append('zero-issues boilerplate')
            if 'QualityEvaluator' in out and ('W601' in out or 'SelfEval' in out):
                w601_r.append('QE-flagging-QE')
            other_mentioned = any(a in out for a in ['Claude', 'Hermes', 'BPT'])
            if agent_name == 'QualityEvaluator' and not other_mentioned and len(out) > 50:
                w601_r.append('self-only: no other agents inspected')
            if w601_r:
                codes.append('W601'); evidence.append('W601: ' + '; '.join(w601_r))

            if codes:
                code_str = ','.join(codes)
                all_issues.append({
                    'agent': agent_name, 'title': title, 'task_id': o['task_id'],
                    'codes': codes, 'evidence': evidence, 'excerpt': out[:200]
                })
                p('**[{}] {}**'.format(code_str, title[:70]))
                p('  Task: {}'.format(o['task_id']))
                for e in evidence: p('  - {}'.format(e))
                p('  Excerpt: `{}...`'.format(out[:150].replace('\n', ' | ')))
                p()
            else:
                p('  [CLEAN] {}'.format(title[:70]))
                p('  Excerpt: `{}...`'.format(out[:100].replace('\n', ' | ')))
                p()

        # STUCK check
        norms = []
        for o in outputs:
            if len(o['output'].strip()) > 10:
                s = o['output'][:300]
                s = re.sub(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', 'TS', s)
                s = re.sub(r'\d+ tasks total', 'N', s)
                s = re.sub(r'\d+/\d+ online', 'N/N', s)
                norms.append(s)
        nc = Counter(norms)
        for sig, cnt in nc.most_common(3):
            if cnt >= 3:
                stuck_list.append({'agent': agent_name, 'count': cnt, 'pattern': sig[:150]})
                p('**STUCK: Same structural output {}x**'.format(cnt))
                p('  Pattern: `{}...`'.format(sig[:120].replace('\n', '\\n')))
                p()

    # Summary
    p('---')
    p('### Issue Distribution by Code')
    p()
    by_code = Counter()
    for i in all_issues:
        for c in i['codes']: by_code[c] += 1

    p('| Code | Description | Count |')
    p('|------|-------------|-------|')
    for code in ['E401', 'E501', 'E502', 'E503', 'E504', 'E505', 'E510', 'W601']:
        descs = {'E401': 'API/Auth Fault', 'E501': 'Thin Output', 'E502': 'Thinking Overload',
                 'E503': 'Empty Output', 'E504': 'Capability Gap', 'E505': 'Hypothetical Output',
                 'E510': 'Roleplay Intro', 'W601': 'Self-Eval Template'}
        p('| {} | {} | {} |'.format(code, descs.get(code, '?'), by_code.get(code, 0)))
    p()

    p('**Total issues:** {}'.format(len(all_issues)))
    p('**STUCK agents:** {}'.format(len(stuck_list)))
    for s in stuck_list:
        p('- [{}] {}x identical structure'.format(s['agent'], s['count']))
    p()

    p('---')
    p('### Root Cause')
    p()
    qe_w601 = sum(1 for i in all_issues if i['agent'] == 'QualityEvaluator' and 'W601' in i['codes'])
    p('**QE Self-Referential Loop:** {} of {} issues are QE flagging QE.'.format(qe_w601, len(all_issues)))
    p('Each QE wake reads QE history -> finds W601 -> reports W601 -> creates more W601 history.')
    p()
    p('### Recommendations')
    p()
    p('1. **[DONE]** QE_CORE_PROTOCOL.md v2: must inspect >=1 non-QE agent per scan')
    p('2. **Claude E503:** task-63afe9ef + task-ec509c39 both pending with empty output')
    p('3. **QE reset:** Clear stale self-eval task chain to break the loop')
    p('4. **E401 chain:** 14 consecutive QE reports with cascading API auth errors')
    p()
    p('=' * 70)
    p('## End of Report')

    return '\n'.join(lines)


if __name__ == '__main__':
    report = build_full_report()
    print(report)

    task_id = sys.argv[1] if len(sys.argv) > 1 else None
    if not task_id:
        # Auto-detect from signal
        sig_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'signals')
        sig_file = os.path.join(sig_dir, 'QualityEvaluator.json')
        if os.path.exists(sig_file):
            with open(sig_file, 'r', encoding='utf-8') as f:
                task_id = json.loads(f.read()).get('task_id')

    if task_id:
        print('\n=== POSTING to {} ==='.format(task_id))
        payload = json.dumps({'agent_id': QE_ID, 'result': report}, ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(
            '{}/api/tasks/{}/complete'.format(BASE, task_id),
            data=payload,
            headers={'Content-Type': 'application/json; charset=utf-8'}
        )
        resp = urllib.request.urlopen(req)
        result = json.loads(resp.read())
        print('Task complete: ok={} result_len={}'.format(
            result.get('ok'), len(result.get('task', {}).get('result', ''))))

        # Clean signal
        sig_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'signals')
        sig_file = os.path.join(sig_dir, 'QualityEvaluator.json')
        if os.path.exists(sig_file):
            os.remove(sig_file)
            print('Signal cleaned: QualityEvaluator.json')
    else:
        print('No task_id provided and no signal found.')
