"""Generate A2A frontend with Qwen3-Coder (Bailian)"""
import json, os, urllib.request, time, re

# Try DeepSeek first (known to work), then Qwen
USE_QWEN = True
QWEN_KEY = os.environ.get('BAILIAN_API_KEY', '')
DEEPSEEK_KEY = os.environ.get('DEEPSEEK_API_KEY', '')

prompt = r"""Write a complete single-file HTML page for an Agent-to-Agent (A2A) communication platform.

Output ONLY complete HTML code. No markdown fences. No explanations.

## Layout (full viewport, no body scroll)
- Left sidebar 260px fixed: Agents + Tasks + Stats
- Right: header + scrollable message stream + fixed input bar

## Dark Theme Colors
- bg: #0d1117, card: #161b22, border: #30363d
- accent: #3fb950 (green), blue: #58a6ff, orange: #d2991d, red: #f85149
- text: #e6edf3, secondary: #8b949e

## Sidebar Content
- "A2A" title with green dot
- AGENTS section: each with online dot, name, capability pills
- TASKS section: pending count badge, list with status indicators
- Stats footer: online count, pending tasks, uptime seconds
- "+" button to open task creation modal

## Message Types (3px left border color coding)
- chat: #30363d border, bubble style
- task_create: #58a6ff border, show title+priority badge+capability tags
- task_claim: #d2991d border, show who claimed
- task_complete: #3fb950 border, result preview + expand on click
- task_fail: #f85149 border, error text
- agent_register/agent_offline: centered thin #8b949e text, no border
- system: centered #8b949e text

## Message Cards
- Sender name in bold #e6edf3, timestamp right-aligned #8b949e
- Task cards show inline capability tags (small rounded pills with #58a6ff bg)
- Priority badge: high=#f85149 pill, normal=#d2991d pill
- Complete/fail cards clickable to expand result section
- Max 200 messages in DOM (trim oldest)

## Input Bar (fixed bottom)
- Auto-resize textarea with placeholder "Type a message..."
- Send button with paper-plane SVG icon (green accent)
- Small "+" button to toggle task creation form

## Task Creation Modal
- Overlay with centered card
- Fields: title input, description textarea, capabilities comma-separated, priority select (high/normal/low)
- Submit calls POST /api/tasks

## JavaScript
- Poll GET /api/messages?since=timestamp every 1.5 seconds
- Poll GET /api/agents every 5 seconds for sidebar update
- POST /api/send {sender, content} on send
- GET /api/health on load
- Track last_msg_ts to avoid duplicates
- Auto-scroll on new messages unless user scrolled up
- Floating "scroll to bottom" button when scrolled up (smooth scroll)
- Click task card to toggle result/error expansion
- timestamp formatting: if today show HH:MM:SS, else show date

## Animation
- @keyframes msgFadeIn: opacity 0->1 + translateY 8px->0, 0.3s
- transition: all 0.2s on buttons, sidebar items hover

## Font
- body: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif
- code: 'SF Mono', 'Consolas', monospace

## Title
- Browser tab: "A2A Platform"
- Header: "A2A" with health dot

Write ALL the code. Complete, working, production quality."""

model = 'qwen3-coder-plus'  # Qwen specialist coding model
key = QWEN_KEY
url = 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions'

body = json.dumps({
    'model': model,
    'messages': [{'role': 'user', 'content': prompt}],
    'max_tokens': 16000,
    'temperature': 0.2,
}).encode()

req = urllib.request.Request(url, data=body, headers={
    'Content-Type': 'application/json',
    'Authorization': f'Bearer {key}',
})

print(f'Calling {model} via Bailian...')
start = time.time()
resp = urllib.request.urlopen(req, timeout=300)
elapsed = time.time() - start
data = json.loads(resp.read())
content = data['choices'][0]['message']['content']
tokens = data['usage']['total_tokens']
print(f'Done: {elapsed:.0f}s, {len(content)} chars, {tokens} tokens')

# Clean content
content = content.strip()
if content.startswith('```html'):
    content = content[7:]
elif content.startswith('```'):
    content = content[3:]
if content.endswith('```'):
    content = content[:-3]
content = content.strip()

# Validate it starts with <!DOCTYPE
if not content.lower().startswith('<!doctype'):
    # Try to find HTML in the response
    m = re.search(r'<!DOCTYPE html>.*?</html>', content, re.DOTALL | re.IGNORECASE)
    if m:
        content = m.group(0)
        print('Extracted HTML from response')

path = 'd:/ClothesNetData/chat-platform/index_new.html'
with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print(f'Saved: {path} ({len(content)} chars)')
print('Preview:')
print(content[:300])
