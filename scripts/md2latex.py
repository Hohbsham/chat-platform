"""Convert ARXIV_REPORT.md to arXiv-compatible LaTeX."""
import re, sys

with open(r"d:\ClothesNetData\chat-platform\ARXIV_REPORT.md", encoding="utf-8") as f:
    report = f.read()

latex = r"""\documentclass[11pt]{article}
\usepackage[utf8]{inputenc}
\usepackage[margin=2.5cm]{geometry}
\usepackage{hyperref}
\usepackage{enumitem}
\usepackage{listings}
\usepackage{xcolor}
\definecolor{codebg}{rgb}{0.95,0.95,0.95}
\lstset{backgroundcolor=\color{codebg}, basicstyle=\ttfamily\small, breaklines=true}

\title{A2A Platform: OS-Level Wake-Up for Autonomous\\Multi-Agent Quality Inspection}
\author{Zi Xu Yang (Hohbsham), Claude (Anthropic)}
\date{July 14, 2026}

\begin{document}
\maketitle
\begin{abstract}
"""

# Extract abstract (text between ## Abstract and ## 1.)
m = re.search(r'## Abstract\n\n(.*?)\n\n## 1\.', report, re.DOTALL)
if m:
    latex += m.group(1).strip() + "\n"
latex += r"\end{abstract}" + "\n\n"

# Get body (everything after the abstract)
body_match = re.search(r'## 1\. Introduction', report)
if body_match:
    body = report[body_match.start():]
else:
    body = report

# Convert markdown to LaTeX
body = re.sub(r'^## (\d)\. (.+)$', r'\n\\section{\2}', body, flags=re.MULTILINE)
body = re.sub(r'^### (\d)\.(\d) (.+)$', r'\n\\subsection{\3}', body, flags=re.MULTILINE)
body = re.sub(r'\*\*(.+?)\*\*', r'\\textbf{\1}', body)
body = re.sub(r'`([^`]+)`', r'\\texttt{\1}', body)

# Code blocks
body = re.sub(r'```(\w*)\n(.*?)```', r'\n\\begin{lstlisting}\n\2\n\\end{lstlisting}\n', body, flags=re.DOTALL)

# Bullet lists
lines = body.split('\n')
result = []
in_list = False
for line in lines:
    if line.strip().startswith('- '):
        if not in_list:
            result.append(r'\begin{itemize}')
            in_list = True
        result.append(r'\item ' + line.strip()[2:])
    else:
        if in_list:
            result.append(r'\end{itemize}')
            in_list = False
        result.append(line)
if in_list:
    result.append(r'\end{itemize}')
body = '\n'.join(result)

# Hyperlinks
body = re.sub(r'\[(.+?)\]\((.+?)\)', r'\\href{\2}{\1}', body)

latex += body
latex += '\n' + r'\end{document}'

out = r"C:\Users\YANGZ\Desktop\arxiv_report.tex"
with open(out, 'w', encoding='utf-8') as f:
    f.write(latex)
print(f"Done: {out} ({len(latex)} chars)")
