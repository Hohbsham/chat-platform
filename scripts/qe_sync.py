"""
QE Sync — Read what the platform QE has done since last check.
Call this BEFORE responding to the user about platform matters.
Returns: list of recently completed QE tasks with scores and findings.

Usage: python qe_sync.py [--since MINUTES]
"""
import sys, io, os, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8') if hasattr(sys.stdout, 'buffer') else sys.stdout

import db

since_minutes = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[1] == '--since' else 30
cutoff = time.time() - (since_minutes * 60)

tasks = [t for t in db.task_all()
         if 'QualityEvaluator' in str(t.get('completed_by', ''))
         and t.get('completed_at', 0) > cutoff]

if not tasks:
    print(f"QE_IDLE|{since_minutes}m|0 tasks")
    sys.exit(0)

# Build summary
print(f"QE_ACTIVE|{since_minutes}m|{len(tasks)} tasks")
for t in tasks:
    result = t.get('result', '') or ''
    # Extract key info
    platform_status = ''
    blocked = ''
    evals_count = ''
    for line in result.split('\n'):
        if 'Platform Status' in line:
            platform_status = line.split('**')[1] if '**' in line else line.strip()
        if 'blocked_agents' in line:
            import re
            m = re.search(r'"blocked_agents":\s*\[(.*?)\]', result)
            if m and m.group(1).strip():
                blocked = f"BLOCKED: {m.group(1)}"
        if 'Evaluated:' in line:
            evals_count = line.strip()

    ts = time.strftime('%H:%M', time.localtime(t.get('completed_at', 0)))
    title = t.get('title', '')[:50]
    print(f"  [{ts}] {title}")
    if platform_status:
        print(f"    Status: {platform_status}")
    if blocked:
        print(f"    {blocked}")
