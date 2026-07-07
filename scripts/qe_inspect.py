"""
QE Full Inspection — 8-dimension detection. Called by Cron or manually.
Outputs structured report. Use this, not ad-hoc Bash one-liners.
"""
import sys, io, os, json, time, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8') if hasattr(sys.stdout, 'buffer') else sys.stdout

import db
from collections import Counter

all_tasks = db.task_all()
agents = db.agent_all()
online = [a for a in agents if a['status'] != 'offline']
thin_agents = [a for a in agents if not a.get('verified')]
thin_online = [a for a in thin_agents if a['status'] != 'offline']

findings = []
output_patterns = Counter()
roleplay_count = 0
self_eval_loop = 0

for t in all_tasks:
    if t['status'] != 'completed':
        continue
    agent_name = (t.get('completed_by', '') or '').split('-')[0]
    result = t.get('result', '') or ''
    issues = []

    # 1. E401: API failure
    if re.search(r'(?i)(401|403|500|Authentication\s+Fails|API\s+error|invalid.*key)', result):
        issues.append('E401:API fail')

    # 2. E510: Roleplay
    if re.search(r'(?i)^We are \w+, (an AI|a Data|a BPT)', result[:100]):
        issues.append('E510:Roleplay')
        roleplay_count += 1

    # 3. E501/E502: Thinking ratio
    if '<!--thinking-->' in result:
        parts = result.split('<!--/thinking-->')
        thinking = parts[0].replace('<!--thinking-->', '').strip()
        content = parts[-1].strip() if len(parts) > 1 else ''
        t_len, c_len = len(thinking), len(content)
        if c_len < 50:
            issues.append(f'E501:Thin({c_len}c/{t_len}c)')
        elif t_len > c_len * 3:
            issues.append(f'E502:ThinkHeavy({t_len//max(c_len,1)}x)')

    # 4. E503: Empty
    stripped = result.strip().strip('<!->\n\r ')
    if len(stripped) < 20:
        issues.append('E503:Empty')
    elif len(stripped) < 100 and agent_name not in ('Claude', 'QualityEvaluator'):
        issues.append(f'W504:Short({len(stripped)}c)')

    # 5. W601: Self-eval template
    plain = result.replace('**', '')
    if 'Issues found: 0' in plain and 'All outputs clean' in plain and agent_name == 'QualityEvaluator':
        issues.append('W601:SelfEvalTemplate')
        self_eval_loop += 1

    # 6. Repeated output tracking
    sig = f'{agent_name}:{stripped[:80]}'
    output_patterns[sig] += 1

    if issues:
        issues_str = ', '.join(issues)
        findings.append(f'[{agent_name}] {t["title"][:40]}: {issues_str}')

# 7. STUCK: >3 identical outputs
for sig, count in output_patterns.most_common(5):
    if count >= 3:
        agent = sig.split(':')[0]
        findings.append(f'STUCK: [{agent}] same output {count}x')

# 8. Thin agent audit
if thin_online:
    thin_names = ', '.join(a['name'] for a in thin_online)
    findings.append(f'THIN: {len(thin_online)} unverified: {thin_names}')

# Report
report = f'''## QualityEvaluator 8-dim Inspection

**Platform:** {len(online)}/{len(agents)} online | {len(all_tasks)} tasks | {len(thin_online)} thin agents
**Issues:** {len(findings)}
{chr(10).join(findings) if findings else '- All clean.'}
**Self-eval loops:** {self_eval_loop}
**Time:** {time.strftime("%H:%M:%S")}'''

print(report)

# Also write to file for Cron consumption
with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
          'signals', '.last_inspection.txt'), 'w', encoding='utf-8') as f:
    f.write(report)
