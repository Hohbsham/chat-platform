"""Generate architecture diagrams and training curves for all repos using matplotlib."""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import numpy as np
import os

OUT = r"d:\ClothesNetData\chat-platform"
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'DejaVu Sans']

# ── Shared helpers ──
def draw_box(ax, x, y, w, h, text, color, fontsize=10, bold=False):
    rect = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.15",
                          facecolor=color, edgecolor='white', linewidth=1.5, alpha=0.9)
    ax.add_patch(rect)
    weight = 'bold' if bold else 'normal'
    ax.text(x + w/2, y + h/2, text, ha='center', va='center', fontsize=fontsize,
            color='white', weight=weight)

def draw_arrow(ax, x1, y1, x2, y2, color='#888888', lw=1.5):
    ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle='->', color=color, lw=lw))

# ══════════════════════════════════════════════════════════════
# 1. chat-platform Architecture Diagram
# ══════════════════════════════════════════════════════════════

def draw_chat_platform_arch():
    fig, ax = plt.subplots(1, 1, figsize=(14, 9))
    ax.set_xlim(0, 14); ax.set_ylim(0, 9)
    ax.axis('off')
    ax.set_facecolor('#1a1a2e')
    box = lambda *a, **kw: draw_box(ax, *a, **kw)
    arrow = lambda *a, **kw: draw_arrow(ax, *a, **kw)

    # Title
    ax.text(7, 8.5, 'A2A Chat Platform v2 — Architecture Overview', ha='center',
            fontsize=16, color='white', weight='bold')

    # Client Layer
    box(0.3, 6.5, 3.5, 1.5, 'Web UI (index.html)\nWebSocket Real-time', '#1677ff')
    box(4.2, 6.5, 3.5, 1.5, 'Agent Client (agent.py)\nClaude / Cursor / OpenClaw', '#722ed1')
    box(8.3, 6.5, 3.5, 1.5, 'CLI / API Consumer\ncurl / custom scripts', '#13c2c2')

    # Server Layer
    box(0.3, 3.8, 4.0, 2.0, 'HTTP REST Server\nPort 8765\n/api/tasks /api/agents\n/api/messages /api/health', '#fa8c16', 9)
    box(4.8, 3.8, 4.0, 2.0, 'WebSocket Server\nPort 8766\nReal-time event push\nbidirectional streaming', '#52c41a', 9)
    box(9.3, 3.8, 4.0, 2.0, 'Task State Machine\npending→claimed→working\n→input_required→completed\n(A2A Protocol compliant)', '#ff4d4f', 9)

    # Data Layer
    box(0.3, 1.0, 4.0, 2.0, 'Agent Store\n(role/goal/backstory)\nCrewAI-inspired identity', '#b37feb', 9)
    box(4.8, 1.0, 4.0, 2.0, 'Task Store\n(broadcast/groupchat/\napproval/context chain)', '#faad14', 9)
    box(9.3, 1.0, 4.0, 2.0, 'Message Store\nUnified event log\nWebSocket broadcast', '#1677ff', 9)

    # Arrows between layers
    for x in [2.0, 6.5, 10.5]:
        arrow(x, 6.5, x, 5.8, '#888')
    for x in [2.0, 6.5, 10.5]:
        arrow(x, 3.8, x, 3.0, '#888')

    # Mode badges
    ax.text(7, 0.3, 'Modes: Broadcast | GroupChat | HITL Approval | Context Chaining',
            ha='center', fontsize=11, color='#aaa')

    plt.tight_layout()
    path = os.path.join(OUT, 'architecture.png')
    plt.savefig(path, dpi=150, bbox_inches='tight', facecolor='#1a1a2e')
    plt.close()
    print(f'[OK] {path}')

# ══════════════════════════════════════════════════════════════
# 2. Task State Machine Diagram
# ══════════════════════════════════════════════════════════════

def draw_task_state_machine():
    fig, ax = plt.subplots(1, 1, figsize=(14, 5))
    ax.set_xlim(0, 14); ax.set_ylim(0, 5)
    ax.axis('off')
    ax.set_facecolor('#1a1a2e')
    box = lambda *a, **kw: draw_box(ax, *a, **kw)
    arrow = lambda *a, **kw: draw_arrow(ax, *a, **kw)

    states = [
        (0.5, 2.5, 'PENDING', '#1677ff'),
        (3.2, 2.5, 'CLAIMED', '#fa8c16'),
        (5.9, 2.5, 'WORKING', '#52c41a'),
        (8.6, 4.0, 'INPUT_REQUIRED', '#faad14'),
        (8.6, 1.0, 'FAILED', '#ff4d4f'),
        (11.3, 2.5, 'COMPLETED', '#52c41a'),
        (11.3, 1.0, 'CANCELLED', '#ff4d4f'),
    ]

    for x, y, label, color in states:
        rect = FancyBboxPatch((x, y), 2.2, 1.0, boxstyle="round,pad=0.1",
                               facecolor=color, edgecolor='white', linewidth=2, alpha=0.85)
        ax.add_patch(rect)
        ax.text(x+1.1, y+0.5, label, ha='center', va='center', fontsize=12,
                color='white', weight='bold')

    # Transitio---ns
    transitions = [
        (2.7, 3.0, 3.2, 3.0, 'agent claims', '#888'),
        (5.4, 3.0, 5.9, 3.0, 'starts working', '#888'),
        (7.0, 3.2, 8.6, 4.3, 'needs input', '#faad14'),
        (9.7, 3.8, 7.0, 3.2, 'input provided', '#52c41a'),
        (7.0, 2.5, 8.6, 1.5, 'error/exception', '#ff4d4f'),
        (9.7, 3.0, 11.3, 3.0, 'task completed', '#52c41a'),
        (7.0, 2.0, 11.3, 1.5, 'manual cancel', '#ff4d4f'),
    ]

    for x1, y1, x2, y2, label, color in transitions:
        ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                     arrowprops=dict(arrowstyle='->', color=color, lw=2, connectionstyle='arc3,rad=0.1'))
        mx, my = (x1+x2)/2, (y1+y2)/2 + 0.2
        ax.text(mx, my, label, ha='center', fontsize=8, color=color, style='italic')

    ax.text(7, 4.8, 'Task State Machine — A2A Protocol Compliant', ha='center',
            fontsize=14, color='white', weight='bold')

    plt.tight_layout()
    path = os.path.join(OUT, 'task_state_machine.png')
    plt.savefig(path, dpi=150, bbox_inches='tight', facecolor='#1a1a2e')
    plt.close()
    print(f'[OK] {path}')


# ══════════════════════════════════════════════════════════════
# 3. LanderPi Architecture Diagram
# ══════════════════════════════════════════════════════════════

def draw_landerpi_arch():
    fig, ax = plt.subplots(1, 1, figsize=(14, 7))
    ax.set_xlim(0, 14); ax.set_ylim(0, 7)
    ax.axis('off')
    ax.set_facecolor('#0d1117')
    box = lambda *a, **kw: draw_box(ax, *a, **kw)
    arrow = lambda *a, **kw: draw_arrow(ax, *a, **kw)

    ax.text(7, 6.6, 'LanderPi — Embodied AI Agent Architecture', ha='center',
            fontsize=15, color='white', weight='bold')

    # Input layer
    box_asr = (0.5, 4.5, 3.0, 1.5, 'ASR Input\nWhisper-1\nvoice→text', '#1677ff')
    box_cam = (4.0, 4.5, 3.0, 1.5, 'Vision Input\nDepth Camera\nRGB-D', '#722ed1')
    box_lidar = (7.5, 4.5, 3.0, 1.5, 'LiDAR Input\nMS200\nPoint Cloud', '#13c2c2')
    box_imu = (11.0, 4.5, 2.5, 1.5, 'IMU + Odometry\nEKF Fusion\nPose Estimation', '#fa8c16')

    for x, y, w, h, t, c in [box_asr, box_cam, box_lidar, box_imu]:
        rect = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.15",
                              facecolor=c, edgecolor='white', linewidth=1.5, alpha=0.85)
        ax.add_patch(rect)
        ax.text(x+w/2, y+h/2, t, ha='center', va='center', fontsize=10, color='white')

    # LLM Reasoning
    box(3.5, 2.2, 7.0, 1.5, 'LLM Intent Understanding\nLlama-3.1-8B: parse user goal, plan navigation route',
        '#52c41a', 11, bold=True)

    # Navigation stack
    box(0.5, 0.3, 3.0, 1.3, 'Mapping\nRTAB-VSLAM\n3D Map', '#b37feb', 9)
    box(4.0, 0.3, 3.0, 1.3, 'Localization\nAMCL\nParticle Filter', '#faad14', 9)
    box(7.5, 0.3, 3.0, 1.3, 'Planning\nThetaStar + TEB\nGlobal + Local', '#ff4d4f', 9)
    box(11.0, 0.3, 2.5, 1.3, 'Motor Control\nSTM32\nMecanum Wheels', '#1677ff', 9)

    # Arrows
    for cx in [2.0, 5.5, 9.0, 12.2]:
        ax.annotate('', xy=(cx, 4.5), xytext=(cx, 3.7),
                     arrowprops=dict(arrowstyle='->', color='#888', lw=2))
    for cx in [2.0, 5.5, 9.0, 12.2]:
        ax.annotate('', xy=(cx, 2.2), xytext=(cx, 1.6),
                     arrowprops=dict(arrowstyle='->', color='#888', lw=2))

    ax.text(7, 0.05, 'Hardware: Raspberry Pi 5 + ROS2 Humble + MS200 LiDAR + Mic Array + STM32',
            ha='center', fontsize=9, color='#666')

    plt.tight_layout()
    path = r'D:\ClothesNetData\chat-platform\landerpi_arch.png'
    plt.savefig(path, dpi=150, bbox_inches='tight', facecolor='#0d1117')
    plt.close()
    print(f'[OK] {path}')


# ══════════════════════════════════════════════════════════════
# 4. Buffett-Munger Training Curve
# ══════════════════════════════════════════════════════════════

def draw_training_curve():
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5))
    fig.patch.set_facecolor('#0d1117')

    # Round data
    rounds = ['R1\nCoca-Cola', 'R2\nMoutai', 'R3\nYili', 'R4\nMidea vs Gree']
    scores = [3, 3, 5, 5]  # Final scores
    dimensions = {
        'Business Essence':     [2, 3, 4, 5],
        'Moat Analysis':        [2, 2, 3, 5],
        'Management Audit':     [0, 1, 3, 5],
        'Shareholder Return':   [0, 1, 4, 5],
        'Inversion Thinking':   [1, 4, 4, 5],
        'Profit/Loss Duality':  [0, 2, 4, 5],
        'Valuation Sweet Spot': [0, 1, 3, 5],
    }

    # Plot 1: Dimension evolution
    x = np.arange(len(rounds))
    colors = ['#1677ff', '#52c41a', '#fa8c16', '#722ed1', '#ff4d4f', '#13c2c2', '#faad14']
    for (dim, values), c in zip(dimensions.items(), colors):
        ax1.plot(x, values, 'o-', color=c, linewidth=2.5, markersize=8, label=dim, alpha=0.9)

    ax1.set_xticks(x); ax1.set_xticklabels(rounds, fontsize=9, color='white')
    ax1.set_ylabel('Score (1-5)', fontsize=11, color='white')
    ax1.set_title('7-Dimension Capability Evolution', fontsize=13, color='white', weight='bold')
    ax1.set_ylim(-0.5, 5.5); ax1.grid(alpha=0.15, color='white')
    ax1.legend(fontsize=7, loc='upper left', facecolor='#1a1a2e', edgecolor='#333', labelcolor='white')
    ax1.set_facecolor('#0d1117')
    ax1.tick_params(colors='white')

    # Plot 2: Overall score + bar
    ax2.bar(x, scores, color=['#ff4d4f','#fa8c16','#52c41a','#1677ff'], alpha=0.85, edgecolor='white', linewidth=1.5)
    for i, s in enumerate(scores):
        ax2.text(i, s + 0.1, f'{"⭐"*s}', ha='center', fontsize=18)

    ax2.set_xticks(x); ax2.set_xticklabels(rounds, fontsize=9, color='white')
    ax2.set_ylabel('Overall Rating (1-5)', fontsize=11, color='white')
    ax2.set_title('RL Training: Round-by-Round Score', fontsize=13, color='white', weight='bold')
    ax2.set_ylim(0, 6); ax2.grid(alpha=0.15, color='white', axis='y')
    ax2.set_facecolor('#0d1117')
    ax2.tick_params(colors='white')

    fig.suptitle('Buffett-Munger Agent — RL Training Trajectory (4 Rounds)', fontsize=15, color='white', weight='bold', y=1.01)
    plt.tight_layout()

    path = r'D:\ClothesNetData\chat-platform\buffett_training_curve.png'
    plt.savefig(path, dpi=150, bbox_inches='tight', facecolor='#0d1117')
    plt.close()
    print(f'[OK] {path}')


# ══════════════════════════════════════════════════════════════
# 5. Buffett-Munger Agent Architecture
# ══════════════════════════════════════════════════════════════

def draw_buffett_agent_arch():
    fig, ax = plt.subplots(1, 1, figsize=(14, 8))
    ax.set_xlim(0, 14); ax.set_ylim(0, 8)
    ax.axis('off')
    ax.set_facecolor('#0d1117')
    box = lambda *a, **kw: draw_box(ax, *a, **kw)
    arrow = lambda *a, **kw: draw_arrow(ax, *a, **kw)

    ax.text(7, 7.7, 'Buffett-Munger Agent — RL Training System Architecture', ha='center',
            fontsize=15, color='white', weight='bold')

    # Input
    box(5.0, 6.3, 4.0, 1.0, 'User Question\n"Analyze Moutai"', '#1677ff', 10, True)

    # Agent Processing
    box(5.0, 4.3, 4.0, 1.5, 'Agent Processing\n7-Dimension Framework\nBusiness Essence→Moat→Mgmt\n→Return→Inversion→Duality→Value', '#722ed1', 9)

    # Output
    box(5.0, 2.5, 4.0, 1.3, 'Structured Output\n🟢🟡🔴 Summary Table\nCompetitor Comparison\nEntry/Exit Price Points', '#52c41a', 9)

    # Human Feedback Loop
    box(11.0, 4.5, 2.5, 2.0, 'Human Rating\n1-5⭐ per dimension\nSpecific Feedback', '#fa8c16', 9)

    # CLAUDE.md update
    box(0.5, 4.5, 2.5, 2.0, 'CLAUDE.md\nAuto-evolve\nBehavior solidified\nfor next session', '#ff4d4f', 9)

    # Knowledge base
    box(5.0, 0.3, 4.0, 1.5, 'Knowledge Base\n23 Books + 181 Buffett Letters\n30 Mental Models + Checklist', '#13c2c2', 9)

    # Skills
    box(0.5, 1.5, 2.5, 1.5, 'Skills\n/book-tutor\n/deep-analysis\n/deep-research', '#b37feb', 9)

    # Arrows
    arrow_pairs = [
        (7, 6.3, 7, 5.8, '#888'),
        (7, 4.3, 7, 3.8, '#888'),
        (9, 5.0, 11, 5.5, '#fa8c16'),   # output → human
        (11.5, 4.5, 9, 3.8, '#fa8c16'),  # human → agent (feedback)
        (5, 5.0, 3, 5.5, '#ff4d4f'),     # agent → CLAUDE.md
        (3, 4.5, 5, 4.8, '#ff4d4f'),     # CLAUDE.md → agent
        (7, 2.5, 7, 1.8, '#13c2c2'),     # output → knowledge base
    ]

    for x1, y1, x2, y2, c in arrow_pairs:
        ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                     arrowprops=dict(arrowstyle='->', color=c, lw=2.5, connectionstyle='arc3,rad=0.2'))

    # Feedback loop label
    ax.text(9.5, 5.8, 'RL Feedback\nLoop', ha='center', fontsize=9, color='#fa8c16', weight='bold')

    plt.tight_layout()
    path = r'D:\ClothesNetData\chat-platform\buffett_agent_arch.png'
    plt.savefig(path, dpi=150, bbox_inches='tight', facecolor='#0d1117')
    plt.close()
    print(f'[OK] {path}')


# ── Run all ──
if __name__ == '__main__':
    draw_chat_platform_arch()
    draw_task_state_machine()
    draw_landerpi_arch()
    draw_training_curve()
    draw_buffett_agent_arch()
    print('\nAll diagrams generated!')
