"""Quick scan: evaluate all completed tasks and post results to chat."""
import sys, io, json, time, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')
import db

HOST = 'http://localhost:8765'

def api_post(path, data):
    body = json.dumps(data, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(HOST + path, data=body,
        headers={'Content-Type': 'application/json; charset=utf-8'})
    return json.loads(urllib.request.urlopen(req).read().decode('utf-8'))

completed = [t for t in db.task_all() if t.get('status') == 'completed']

for task in completed:
    tid = task['task_id']
    title = task.get('title', '')
    result = task.get('result', '') or ''
    agent_name = (task.get('completed_by', '') or '').split('-')[0] or 'unknown'

    issues = []
    score = 5.0

    if 'API error' in result or 'Authentication Fails' in result:
        issues.append('API_FAIL: Agent returned raw API error instead of handling it')
        score -= 3.0

    if '<!--thinking-->' in result:
        parts = result.split('<!--/thinking-->')
        thinking = parts[0].replace('<!--thinking-->', '').strip()
        content = parts[-1].strip() if len(parts) > 1 else ''
        t_len = len(thinking)
        c_len = len(content)
        if c_len < 100:
            issues.append('THIN_OUTPUT: Only %dc content vs %dc thinking' % (c_len, t_len))
            score -= 2.0
        elif t_len > c_len * 2:
            issues.append('THINKING_HEAVY: %dc thinking for %dc output' % (t_len, c_len))
            score -= 0.5
        if 'no actual' in thinking.lower() or 'cannot actually' in thinking.lower():
            issues.append('SELF_AWARE_GAP: Agent internally admits limitation')
            score -= 1.0
    elif len(result) < 50:
        issues.append('EMPTY: Only %dc output' % len(result))
        score -= 4.0

    if result and len(result) > 100:
        has_structure = any(m in result for m in ['##', '###', '|', '```', '- '])
        if not has_structure:
            issues.append('NO_STRUCTURE: Missing markdown formatting')
            score -= 0.3

    final_score = max(0.5, round(score, 1))
    verdict = 'PASS' if final_score >= 3.5 else 'NEEDS_WORK' if final_score >= 2.0 else 'FAIL'

    print('Task: %s' % title[:60])
    print('Agent: %s | Score: %s/5 [%s]' % (agent_name, final_score, verdict))
    for i in issues:
        print('  ! %s' % i)
    print()

    # Post to chat
    lines = ['[QE评估] %s - %s: %s/5 (%s)' % (agent_name, title[:40], final_score, verdict)]
    if issues:
        lines.extend('- %s' % i for i in issues)
    else:
        lines.append('No issues found - clean output.')

    api_post('/api/send', {
        'sender': 'QualityEvaluator',
        'content': '\n'.join(lines),
    })

print('Done. All evaluations posted to chat.')
