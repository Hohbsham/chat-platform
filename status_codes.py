"""
Structured Status Codes — Circuit Breaker for Multi-Agent Communication.

Principle: Downstream agents consume MACHINE-READABLE status codes,
NOT raw natural language. This physically prevents hallucination cascading.

Code format: XNNN where X=E(error) or X=W(warning)
"""

# ═══════════════════════════════════════════════════════════════════
# Status Code Registry
# ═══════════════════════════════════════════════════════════════════

STATUS_CODES = {
    # ── ERROR codes: downstream MUST block/wait/reroute ──
    "E401": {
        "category": "API_AUTH",
        "severity": "BLOCKING",
        "action": "BLOCK_DOWNSTREAM",
        "meaning": "Agent API key is invalid or expired",
        "downstream_rule": "Do NOT read this agent's output. Wait for key fix or reroute.",
    },
    "E402": {
        "category": "API_RATE",
        "severity": "BLOCKING",
        "action": "RETRY_DELAYED",
        "meaning": "Agent hit API rate limit",
        "downstream_rule": "Retry in 60s. Do NOT process partial output.",
    },
    "E501": {
        "category": "THIN_OUTPUT",
        "severity": "DEGRADED",
        "action": "DELEGATE_TOOLED",
        "meaning": "Output too thin: thinking >> content ratio",
        "downstream_rule": "Ignore thin output. Reroute to tooled agent for real data.",
    },
    "E502": {
        "category": "THINKING_HEAVY",
        "severity": "WARNING",
        "action": "COMPRESS_RETRY",
        "meaning": "Internal reasoning is 3x+ longer than actual answer",
        "downstream_rule": "Flag as potential hallucination. Trigger compression.",
    },
    "E503": {
        "category": "EMPTY_OUTPUT",
        "severity": "BLOCKING",
        "action": "REJECT",
        "meaning": "Agent produced effectively no content",
        "downstream_rule": "Reject outright. Do not use as context for any other agent.",
    },
    "E504": {
        "category": "CAPABILITY_GAP",
        "severity": "BLOCKING",
        "action": "REROUTE",
        "meaning": "Agent admits it cannot perform the required task",
        "downstream_rule": "Reroute to agent with matching capabilities. Suspect capability claim.",
    },
    "E505": {
        "category": "HYPOTHETICAL",
        "severity": "DEGRADED",
        "action": "DELEGATE_TOOLED",
        "meaning": "Agent produced hypothetical/simulated output without real data",
        "downstream_rule": "Reject as unreliable. Only tooled agents can produce real data.",
    },
    "E506": {
        "category": "SELF_AWARE_GAP",
        "severity": "BLOCKING",
        "action": "FLAG_SUSPICIOUS",
        "meaning": "Agent internally knows it cannot do the task but submitted anyway",
        "downstream_rule": "Flag agent capability claim as suspicious. Audit registration.",
    },
    "E507": {
        "category": "ORPHANED_TASK",
        "severity": "BLOCKING",
        "action": "REASSIGN",
        "meaning": "Task was claimed but never completed (agent went offline)",
        "downstream_rule": "Cancel stale claim. Re-post task. Notify capable agents.",
    },

    # ── WARNING codes: downstream may continue with caution ──
    "W301": {
        "category": "NO_STRUCTURE",
        "severity": "LOW",
        "action": "WARN",
        "meaning": "Output lacks markdown structure or section headers",
        "downstream_rule": "Continue but flag for formatting improvement.",
    },
    "W302": {
        "category": "EXCESSIVE_LENGTH",
        "severity": "LOW",
        "action": "TRUNCATE",
        "meaning": "Output exceeds 50000 characters",
        "downstream_rule": "Truncate to first 10K chars before passing to other agents.",
    },
    "W303": {
        "category": "LOW_CONFIDENCE",
        "severity": "MEDIUM",
        "action": "REVIEW",
        "meaning": "LLM Judge expressed uncertainty in scoring",
        "downstream_rule": "Use rule-layer score only. Ignore LLM Judge dimension scores.",
    },

    # ── Special: UNCERTAIN (LLM Judge cannot find evidence) ──
    "UNCERTAIN": {
        "category": "JUDGE_UNCERTAIN",
        "severity": "MEDIUM",
        "action": "FALLBACK_RULES",
        "meaning": "LLM Judge could not find evidence to support dimension score",
        "downstream_rule": "Fall back to deterministic rule-layer score. Do NOT use Judge score.",
    },

    # ── OK ──
    "PASS": {
        "category": "OK",
        "severity": "NONE",
        "action": "ALLOW",
        "meaning": "All checks passed. Output is reliable.",
        "downstream_rule": "Safe to use as context for other agents.",
    },
}


def get_code_info(code):
    """Look up a status code. Returns dict with category/severity/action."""
    return STATUS_CODES.get(code, STATUS_CODES["PASS"])


def issue_to_status_code(issue_text):
    """
    Map a natural-language issue string to a structured status code.
    This is the bridge between old string-based issues and new machine-readable codes.

    Examples:
        "API_ERROR: ..." → "E401"
        "THIN_OUTPUT: ..." → "E501"
        "THINKING_HEAVY: ..." → "E502"
    """
    mapping = [
        ("API_ERROR", "E401"),
        ("THIN_OUTPUT", "E501"),
        ("THINKING_HEAVY", "E502"),
        ("EMPTY_OUTPUT", "E503"),
        ("CAPABILITY_GAP", "E504"),
        ("HYPOTHETICAL", "E505"),
        ("SELF_AWARE_GAP", "E506"),
        ("NO_TOOLS", "E505"),  # no tools → same as hypothetical
        ("ORPHANED_TASK", "E507"),
        ("NO_STRUCTURE", "W301"),
        ("output_excessive", "W302"),
    ]
    upper = issue_text.upper()
    for keyword, code in mapping:
        if keyword in upper:
            return code
    return None  # unknown → will be treated as GENERIC


def build_status_report(evaluations):
    """
    Take a list of evaluation dicts and produce a machine-readable status report.
    This is what downstream agents should consume — NOT the raw evaluations.

    Returns:
        {
            "platform_status": "DEGRADED",  # or "HEALTHY" or "BLOCKED"
            "blocked_agents": [...],
            "safe_contexts": [...],
            "actions_taken": [...],
            "per_task": [{code, action, severity, ...}, ...]
        }
    """
    report = {
        "platform_status": "HEALTHY",
        "blocked_agents": [],
        "degraded_agents": [],
        "safe_contexts": [],
        "actions_taken": [],
        "per_task": [],
    }

    for ev in evaluations:
        issues = ev.get("issues", [])
        task_codes = []

        for issue_text in issues:
            code = issue_to_status_code(issue_text)
            if code:
                info = get_code_info(code)
                task_codes.append({
                    "code": code,
                    "action": info["action"],
                    "severity": info["severity"],
                    "category": info["category"],
                    "evidence": issue_text[:100],
                })

                # Track platform status
                if info["severity"] == "BLOCKING":
                    report["platform_status"] = "BLOCKED"
                    agent = ev.get("agent", "unknown")
                    if agent not in report["blocked_agents"]:
                        report["blocked_agents"].append(agent)
                elif info["severity"] == "DEGRADED":
                    if report["platform_status"] != "BLOCKED":
                        report["platform_status"] = "DEGRADED"
                    agent = ev.get("agent", "unknown")
                    if agent not in report["degraded_agents"]:
                        report["degraded_agents"].append(agent)

                # Track remediation actions
                action = info["action"]
                if action not in report["actions_taken"]:
                    report["actions_taken"].append(action)

        # If task had no issues, mark as safe context
        if not issues:
            report["safe_contexts"].append({
                "task_id": ev.get("task_id", ""),
                "agent": ev.get("agent", ""),
                "score": ev.get("score", 0),
            })

        if task_codes:
            report["per_task"].append({
                "task_id": ev.get("task_id", ""),
                "agent": ev.get("agent", ""),
                "score": ev.get("score", 0),
                "verdict": ev.get("verdict", "?"),
                "codes": task_codes,
            })

    return report


def downstream_filter(task_id, output_text, status_report):
    """
    Circuit breaker: check if a task's output is safe for downstream consumption.
    Returns (is_safe, reason, filtered_output_or_None).

    This is the physical isolation point — downstream agents call THIS before
    reading any other agent's output.
    """
    for entry in status_report.get("per_task", []):
        if entry.get("task_id") != task_id:
            continue
        for code_info in entry.get("codes", []):
            if code_info["action"] in ("BLOCK_DOWNSTREAM", "REJECT", "FLAG_SUSPICIOUS"):
                return False, f"BLOCKED by {code_info['code']}: {code_info['evidence'][:80]}", None
            if code_info["action"] == "DELEGATE_TOOLED":
                return False, f"DEGRADED by {code_info['code']}: output is thin/hypothetical, use tooled agent", None
        if entry.get("verdict") == "PASS":
            return True, "SAFE", output_text

    return True, "UNVERIFIED (no status codes found)", output_text
