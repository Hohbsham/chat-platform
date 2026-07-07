"""
QualityEvaluator — Core Agent Output Quality Evaluation Engine.

Three-phase evaluation pipeline:
  Phase 1: Deterministic (code-based) checks — free, fast
  Phase 2: LLM-as-Judge (model-based) scoring — rubric-guided
  Phase 3: Aggregation + DimensionAwareFilter + persistence

Also serves as the CLI entry point for quality commands.

Usage:
  python quality_evaluator.py eval --task-id <id> [--agent-id <id>]
  python quality_evaluator.py quality [--agent <name>] [--domain <domain>] [--trend]
  python quality_evaluator.py calibrate --golden-set <path>
"""
import json, os, re, sys, time, uuid, urllib.request, urllib.error
import db  # v3: SQLite database
from models import Evaluation  # keep dataclass for internal logic

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── AI Config loading (same pattern as agent.py) ──────────────────

def load_ai_config():
    """Load AI API configuration from OpenClaw config or environment."""
    config = {"api_key": None, "base_url": None, "model": None}
    for p in [
        os.path.expanduser("~/.openclaw/openclaw.json"),
        os.path.expanduser("~/.config/openclaw/openclaw.json"),
    ]:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                agents_cfg = cfg.get("agents", {}).get("defaults", {})
                model_str = agents_cfg.get("model", "")
                provider = model_str.split("/")[0] if "/" in model_str else "deepseek"
                model_id = model_str.split("/")[1] if "/" in model_str else model_str
                providers = cfg.get("models", {}).get("providers", {})
                if provider in providers:
                    pcfg = providers[provider]
                    config["base_url"] = pcfg.get("baseUrl", "")
                    config["api_key"] = pcfg.get("apiKey", "")
                    config["model"] = model_str
                break
            except Exception:
                pass
    for key in ["AI_API_KEY", "AI_BASE_URL", "AI_MODEL"]:
        cfg_key = key.replace("AI_", "").lower()
        if os.environ.get(key):
            config[cfg_key] = os.environ[key]
    return config


def call_ai(system_prompt, user_prompt, temperature=0.1, max_tokens=2000):
    """Call AI model. Returns (response_text, error). Temperature low for judging."""
    cfg = load_ai_config()
    if not cfg["api_key"] or not cfg["base_url"]:
        return None, "No AI API configured"

    url = cfg["base_url"].rstrip("/") + "/v1/chat/completions"
    model_name = cfg["model"].split("/")[-1] if "/" in cfg["model"] else cfg["model"]
    body = json.dumps({
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {cfg['api_key']}",
    }
    try:
        req = urllib.request.Request(url, data=body, headers=headers)
        resp = urllib.request.urlopen(req, timeout=90)
        data = json.loads(resp.read().decode("utf-8"))
        msg = data["choices"][0]["message"]
        content = (msg.get("content") or "").strip()
        if not content:
            return None, "AI returned empty response"
        return content, None
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:300]
        return None, f"AI API error {e.code}: {err_body}"
    except Exception as e:
        return None, str(e)


# ── Phase 1: Deterministic Checks ─────────────────────────────────

ERROR_PATTERNS = [
    (r"(?i)i don't have access to", "refusal_access"),
    (r"(?i)as an AI (language model|assistant)", "generic_refusal"),
    (r"(?i)i cannot (help|assist|provide|generate|create)", "refusal_cannot"),
    (r"(?i)apologies.{0,20}(but|however|i.{0,10}unable)", "apology_refusal"),
    (r"(?i)it would be (unethical|inappropriate|irresponsible)", "ethics_refusal"),
    (r"(?i)please (note|be aware|consult|seek).{0,30}(professional|expert|lawyer)", "disclaimer_deflection"),
]


def deterministic_checks(task, agent, output_text):
    """
    Phase 1: Fast, code-based checks before LLM evaluation.
    Returns (checks_dict, flags_list, penalty_score).
    penalty_score: 0.0 = no penalty, up to 0.5 deducted from final score.
    """
    checks = {}
    flags = []
    penalty = 0.0

    # 1. Output length
    text_len = len(output_text) if output_text else 0
    checks["output_length"] = text_len
    if text_len < 20:
        checks["output_too_short"] = True
        flags.append("output_too_short")
        penalty += 0.5
    else:
        checks["output_too_short"] = False
    if text_len > 50000:
        checks["output_excessive"] = True
        flags.append("output_excessive")
    else:
        checks["output_excessive"] = False

    # 2. Structure indicators
    has_sections = bool(re.search(r"(?im)^#{1,3}\s|^[=-]{3,}|^\d+[\.\)]\s|```", output_text or ""))
    has_code = bool(re.search(r"```", output_text or ""))
    checks["has_structure"] = has_sections or has_code
    if not checks["has_structure"] and text_len > 200:
        flags.append("no_visible_structure")
        penalty += 0.1

    # 3. Error pattern detection
    found_patterns = []
    for pattern, tag in ERROR_PATTERNS:
        if re.search(pattern, output_text or ""):
            found_patterns.append(tag)
    checks["error_patterns"] = found_patterns
    if found_patterns:
        flags.extend(f"refusal_pattern:{t}" for t in found_patterns)
        penalty += 0.3

    # 4. Capability match
    task_caps = set(getattr(task, "required_capabilities", task.get("required_capabilities", [])) if isinstance(task, dict) else task.required_capabilities)
    agent_caps = set(getattr(agent, "capabilities", agent.get("capabilities", [])) if isinstance(agent, dict) else agent.capabilities)
    checks["capability_match"] = task_caps.issubset(agent_caps) if task_caps else True
    if not checks["capability_match"]:
        flags.append("capability_mismatch")
        penalty += 0.2

    # 5. Latency check (if timestamps available on task)
    if not isinstance(task, dict):
        created = task.created_at
        completed = task.completed_at
        if created and completed:
            elapsed = completed - created
            checks["latency_s"] = round(elapsed, 1)
            if elapsed < 1.0:
                flags.append("suspiciously_fast")
                penalty += 0.1
            elif elapsed > 600:
                checks["latency_excessive"] = True

    return checks, flags, min(penalty, 0.5)


# ── Core Evaluator ────────────────────────────────────────────────

from eval_rubrics import match_rubric, apply_dimension_filter


class QualityEvaluator:
    """Core evaluation engine for agent output quality assessment."""

    def __init__(self, store_path=None):
        self.store_path = store_path or os.path.join(BASE_DIR, "eval_store.json")
        # v3: use SQLite database for all storage
        self.eval_store = db
        self.agent_store = db
        self.task_store = db

    def evaluate_task(self, task, agent=None):
        """
        Full three-phase evaluation pipeline.
        `task` can be a Task object or dict.
        `agent` can be an Agent object, dict, or None (auto-lookup).
        Returns Evaluation object.
        """
        # Normalize inputs
        if isinstance(task, dict):
            task_id = task.get("task_id", "")
            task_title = task.get("title", "")
            task_desc = task.get("description", "")
            output_text = task.get("result", "") or ""
        else:
            task_id = task.task_id
            task_title = task.title
            task_desc = task.description
            output_text = task.result or ""

        if agent is None and task_id:
            # Try to look up the agent from the task
            if isinstance(task, dict):
                agent_id = task.get("completed_by", task.get("claimed_by", ""))
            else:
                agent_id = task.completed_by or task.claimed_by or ""
            agent = self.agent_store.agent_find(agent_id) if agent_id else None

        if isinstance(agent, dict):
            agent_id = agent.get("agent_id", "")
            agent_name = agent.get("name", "Unknown")
            agent_role = agent.get("role", "")
            agent_goal = agent.get("goal", "")
            agent_backstory = agent.get("backstory", "")
            agent_caps = agent.get("capabilities", [])
        elif agent is not None:
            agent_id = agent.agent_id
            agent_name = agent.name
            agent_role = agent.role
            agent_goal = agent.goal
            agent_backstory = agent.backstory
            agent_caps = agent.capabilities
        else:
            agent_id = ""
            agent_name = "Unknown"
            agent_role = ""
            agent_goal = ""
            agent_backstory = ""
            agent_caps = []

        # Skip if no output to evaluate
        if not output_text or len(output_text.strip()) < 5:
            return self._create_empty_eval(task_id, agent_id, agent_name, agent_role,
                                           "no_output")

        # ── Phase 1: Deterministic checks ──
        stage1, flags, penalty = deterministic_checks(task, agent, output_text)

        # ── Phase 2: LLM-as-Judge ──
        rubric, match_score = match_rubric(agent_caps, agent_name, agent_role)
        domain = rubric.agent_domain

        llm_result = None
        llm_error = None
        try:
            judge_prompt = rubric.build_judge_prompt(
                task_title, task_desc, agent_name, agent_role,
                agent_goal, agent_backstory, output_text,
            )
            raw_response, llm_error = call_ai(
                rubric.judge_system_prompt, judge_prompt, temperature=0.1,
            )
            if raw_response:
                llm_result = self._parse_llm_response(raw_response)
                if llm_result:
                    llm_result["_raw"] = raw_response
        except Exception as e:
            llm_error = str(e)

        # ── Phase 3: Aggregation ──
        eval_id = f"eval-{uuid.uuid4().hex[:8]}"
        timestamp = time.time()

        if llm_result is None:
            # LLM judge failed — store what we have from deterministic checks
            scores = {"overall": max(0, 3.0 - penalty), "dimensions": {}}
            eval_flags = flags + [f"llm_judge_failed:{llm_error[:60]}" if llm_error else "llm_judge_failed"]
            evidence = []
            suggestions = ["LLM evaluation failed — only deterministic checks available."]
            strengths = []
            weaknesses = []
            confidence = 0.1
        else:
            # Merge LLM scores with deterministic penalty
            raw_overall = llm_result.get("overall_score", 3.0)
            dimensions = {}
            evidence = []
            for dim in llm_result.get("dimensions", []):
                dname = dim.get("name", "unknown")
                dimensions[dname] = dim.get("score", 3.0)
                ev = dim.get("evidence", "")
                if ev:
                    evidence.append({"dimension": dname, "quote": str(ev)[:300]})

            scores = {"overall": raw_overall, "dimensions": dimensions}
            filtered_overall, filter_flags = apply_dimension_filter(
                {"overall": raw_overall, "dimensions": dimensions}
            )
            if filtered_overall < raw_overall:
                scores["overall_raw"] = raw_overall
                scores["overall"] = filtered_overall
                flags.extend(filter_flags)

            # Apply deterministic penalty
            if penalty > 0:
                scores["overall"] = round(max(1.0, scores["overall"] - penalty), 1)

            eval_flags = flags
            suggestions = llm_result.get("suggestions", [])
            strengths = llm_result.get("strengths", [])
            weaknesses = llm_result.get("weaknesses", [])
            confidence = llm_result.get("confidence", 0.5)

        evaluation = Evaluation(
            eval_id=eval_id,
            task_id=task_id,
            agent_id=agent_id,
            agent_name=agent_name,
            agent_role=agent_role,
            domain=domain,
            task_title=task_title,
            timestamp=timestamp,
            scores=scores,
            evidence=evidence,
            suggestions=suggestions,
            strengths=strengths,
            weaknesses=weaknesses,
            confidence=confidence,
            flags=eval_flags,
            stage1_checks=stage1,
            judge_raw=llm_result.get("_raw", "") if llm_result else "",
        )

        # Mark self-evaluation if the evaluator is evaluating its own output
        if agent_name in ("QualityEvaluator", "EvalJudge"):
            evaluation.flags.append("self_eval")

        return evaluation

    def _create_empty_eval(self, task_id, agent_id, agent_name, agent_role, reason):
        """Create an evaluation record when there's nothing to evaluate."""
        return Evaluation(
            eval_id=f"eval-{uuid.uuid4().hex[:8]}",
            task_id=task_id,
            agent_id=agent_id,
            agent_name=agent_name,
            agent_role=agent_role,
            domain="generic",
            task_title="(empty output)",
            timestamp=time.time(),
            scores={"overall": 0, "dimensions": {}},
            suggestions=[f"No evaluation possible: {reason}"],
            flags=[reason],
            stage1_checks={"output_length": 0},
        )

    def _parse_llm_response(self, raw_text):
        """Extract JSON from LLM response. Tries multiple strategies."""
        strategies = [
            # Strategy 1: Find JSON block between ```json and ```
            lambda t: re.search(r'```json\s*([\s\S]*?)\s*```', t),
            # Strategy 2: Find JSON block between ``` and ```
            lambda t: re.search(r'```\s*(\{[\s\S]*?\})\s*```', t),
            # Strategy 3: Find outermost {...}
            lambda t: re.search(r'\{[\s\S]*\}', t),
        ]
        for strategy in strategies:
            m = strategy(raw_text)
            if m:
                try:
                    return json.loads(m.group(1) if m.lastindex else m.group(0))
                except (json.JSONDecodeError, IndexError):
                    continue
        return None

    def store(self, evaluation):
        """Persist evaluation record."""
        return self.eval_store.eval_append(evaluation.to_dict())

    def evaluate_and_store(self, task, agent=None):
        """Evaluate and persist in one call. Returns Evaluation."""
        evaluation = self.evaluate_task(task, agent)
        self.store(evaluation)
        return evaluation

    def history(self, agent_id=None, agent_name=None, domain=None, limit=50):
        return self.eval_store.eval_query(agent_id=agent_id, agent_name=agent_name,
                                         domain=domain, limit=limit)

    def trend_analysis(self, agent_id, window=10):
        """Sliding window trend for an agent."""
        evals = self.eval_store.eval_query(agent_id=agent_id, limit=100)
        if len(evals) < 3:
            return {"agent_id": agent_id, "evaluations": len(evals),
                    "trend": "insufficient_data"}

        recent = evals[-window:]
        scores = [e.scores.get("overall", 0) for e in recent]
        avg = round(sum(scores) / len(scores), 2)

        # Compute slope of last N scores
        if len(scores) >= 3:
            n = len(scores)
            x_mean = (n - 1) / 2
            y_mean = sum(scores) / n
            num = sum((i - x_mean) * (s - y_mean) for i, s in enumerate(scores))
            den = sum((i - x_mean) ** 2 for i in range(n))
            slope = round(num / den * 10, 3) if den > 0 else 0  # slope per 10 evals
        else:
            slope = 0

        direction = "improving" if slope > 0.05 else "declining" if slope < -0.05 else "stable"

        return {
            "agent_id": agent_id,
            "window": window,
            "avg_score": avg,
            "slope": slope,
            "direction": direction,
            "scores": scores,
        }

    def pass_at_k(self, agent_id, k=3, threshold=3.0):
        """pass@k metric: fraction of task groups with >=1 score above threshold."""
        evals = self.eval_store.eval_query(agent_id=agent_id, limit=500)
        if not evals:
            return 0.0

        # Group by task_id
        by_task = {}
        for e in evals:
            by_task.setdefault(e.task_id, []).append(e.scores.get("overall", 0))

        passes = 0
        for tid, scores in by_task.items():
            best = max(scores[:k]) if scores else 0
            if best >= threshold:
                passes += 1

        return round(passes / len(by_task), 2) if by_task else 0.0

    def platform_overview(self):
        return self.eval_store.platform_overview()

    def calibrate(self, golden_set_path):
        """
        Calibrate LLM Judge against a golden evaluation set.
        Golden set format: [{task, agent, expected_scores, human_rationale}, ...]
        Returns calibration report dict.
        """
        if not os.path.exists(golden_set_path):
            return {"error": f"Golden set not found: {golden_set_path}"}

        with open(golden_set_path, "r", encoding="utf-8") as f:
            golden = json.load(f)

        results = []
        dim_diffs = {}
        all_errors = []

        for i, entry in enumerate(golden):
            task = entry.get("task", {})
            agent = entry.get("agent", {})
            expected = entry.get("expected_scores", {})

            evaluation = self.evaluate_task(task, agent)
            actual = evaluation.scores

            diff = {
                "index": i,
                "task_title": task.get("title", ""),
                "expected_overall": expected.get("overall", 0),
                "actual_overall": actual.get("overall", 0),
                "dimension_diffs": {},
            }

            for dim_name, exp_score in expected.get("dimensions", {}).items():
                act_score = actual.get("dimensions", {}).get(dim_name, 0)
                diff["dimension_diffs"][dim_name] = round(act_score - exp_score, 2)
                dim_diffs.setdefault(dim_name, []).append(act_score - exp_score)

            overall_err = abs(actual.get("overall", 0) - expected.get("overall", 0))
            all_errors.append(overall_err)
            results.append(diff)

        mae = round(sum(all_errors) / len(all_errors), 2) if all_errors else 0

        dim_bias = {}
        for dname, diffs in dim_diffs.items():
            avg_bias = round(sum(diffs) / len(diffs), 2) if diffs else 0
            dim_bias[dname] = {
                "avg_bias": avg_bias,
                "interpretation": "over-scores" if avg_bias > 0.2 else "under-scores" if avg_bias < -0.2 else "well-calibrated",
            }

        return {
            "golden_set_size": len(golden),
            "mae": mae,
            "dimension_bias": dim_bias,
            "per_entry": results,
            "recommendations": self._calibration_recommendations(dim_bias),
        }

    def _calibration_recommendations(self, dim_bias):
        recs = []
        for dname, info in dim_bias.items():
            if info["interpretation"] == "over-scores":
                recs.append(f"Tighten '{dname}' scoring: judge over-scores by {info['avg_bias']}. Consider stricter level descriptions.")
            elif info["interpretation"] == "under-scores":
                recs.append(f"Relax '{dname}' scoring: judge under-scores by {info['avg_bias']}. Consider more generous level descriptions.")
        if not recs:
            recs.append("All dimensions well-calibrated. No rubric adjustments needed.")
        return recs


# ═══════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════

HOST = os.environ.get("CHAT_HOST", "http://localhost:8765")


def _api_get(path):
    url = f"{HOST}{path}"
    resp = urllib.request.urlopen(url)
    return json.loads(resp.read().decode("utf-8"))


def _api_post(path, data):
    url = f"{HOST}{path}"
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body,
        headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        resp = urllib.request.urlopen(req)
        return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode("utf-8"))


def _safe_print(msg):
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode("ascii"))


def cmd_eval(args):
    """Evaluate a completed task's output quality."""
    evaluator = QualityEvaluator()

    # Fetch task + agent from server, or use local stores
    try:
        task_data = _api_get(f"/api/tasks/{args.task_id}")
    except Exception:
        task_data = evaluator.task_store.task_find(args.task_id)
        if task_data:
            task_data = task_data.to_dict()
        else:
            _safe_print(f"Task not found: {args.task_id}")
            return

    if isinstance(task_data, dict) and task_data.get("status") != "completed":
        _safe_print(f"Task is {task_data.get('status')}, not completed. Evaluating anyway...")

    agent_id = args.agent_id
    if not agent_id:
        if isinstance(task_data, dict):
            agent_id = task_data.get("completed_by") or task_data.get("claimed_by", "")

    agent_data = None
    if agent_id:
        try:
            agents_list = _api_get("/api/agents")
            for a in agents_list:
                if a.get("agent_id") == agent_id:
                    agent_data = a
                    break
        except Exception:
            pass

    evaluation = evaluator.evaluate_task(task_data, agent_data)
    evaluator.store(evaluation)

    # Print formatted report
    _safe_print("")
    _safe_print("=" * 70)
    _safe_print(f"  QUALITY EVALUATION  |  {evaluation.eval_id}")
    _safe_print("=" * 70)
    _safe_print(f"  Agent:    {evaluation.agent_name} ({evaluation.agent_role})")
    _safe_print(f"  Domain:   {evaluation.domain}")
    _safe_print(f"  Task:     {evaluation.task_title[:60]}")
    _safe_print(f"  Score:    {evaluation.scores.get('overall', 'N/A')}/5.0")
    _safe_print(f"  Confidence: {evaluation.confidence:.0%}")
    _safe_print("-" * 70)

    if evaluation.scores.get("dimensions"):
        _safe_print("  Dimension Breakdown:")
        for dname, dscore in evaluation.scores["dimensions"].items():
            bar_len = int(dscore * 4)  # 20 chars max
            bar = "█" * bar_len + "░" * (20 - bar_len)
            _safe_print(f"    {dname:<22s} {bar} {dscore}/5")

    if evaluation.flags:
        _safe_print(f"  Flags: {', '.join(evaluation.flags)}")

    if evaluation.strengths:
        _safe_print("\n  STRENGTHS:")
        for s in evaluation.strengths[:3]:
            _safe_print(f"    + {s}")

    if evaluation.weaknesses:
        _safe_print("\n  WEAKNESSES:")
        for w in evaluation.weaknesses[:3]:
            _safe_print(f"    - {w}")

    if evaluation.suggestions:
        _safe_print("\n  SUGGESTIONS:")
        for i, s in enumerate(evaluation.suggestions[:5], 1):
            _safe_print(f"    {i}. {s}")

    if evaluation.evidence:
        _safe_print("\n  EVIDENCE:")
        for ev in evaluation.evidence[:3]:
            _safe_print(f"    [{ev.get('dimension','')}] \"{ev.get('quote','')[:100]}\"")

    _safe_print("=" * 70)
    _safe_print(f"  Stored as {evaluation.eval_id}")


def cmd_quality(args):
    """View quality reports."""
    evaluator = QualityEvaluator()

    if args.agent:
        stats = evaluator.eval_store.agent_stats(args.agent)
        _safe_print("")
        _safe_print("=" * 60)
        _safe_print(f"  AGENT QUALITY: {args.agent}")
        _safe_print("=" * 60)
        _safe_print(f"  Evaluations: {stats['count']}")
        _safe_print(f"  Avg Score:   {stats['avg_overall']}/5.0")
        _safe_print(f"  Trend:       {stats['trend']}")

        if stats.get("dimensions"):
            _safe_print("\n  Dimension Averages:")
            for dname, dscore in sorted(stats["dimensions"].items()):
                bar_len = int(dscore * 4)
                bar = "█" * bar_len + "░" * (20 - bar_len)
                _safe_print(f"    {dname:<22s} {bar} {dscore}/5")

        if args.trend:
            trend = evaluator.trend_analysis(args.agent)
            _safe_print(f"\n  Trend (last {trend.get('window','?')} evals):")
            _safe_print(f"    Direction: {trend.get('direction','?')}")
            _safe_print(f"    Slope:     {trend.get('slope','?')}")

        if args.pass_at_k:
            pk = evaluator.pass_at_k(args.agent, k=args.pass_at_k)
            _safe_print(f"\n  pass@{args.pass_at_k}: {pk:.0%}")

        # Recent evaluations
        recent = evaluator.history(agent_name=args.agent, limit=5)
        if recent:
            _safe_print("\n  Recent Evaluations:")
            for e in recent:
                score = e.scores.get("overall", "?")
                icon = "🟢" if score >= 4 else "🟡" if score >= 3 else "🔴"
                _safe_print(f"    {icon} {e.task_title[:50]} — {score}/5")

        _safe_print("=" * 60)

    elif args.domain:
        stats = evaluator.eval_store.domain_stats(args.domain)
        _safe_print(f"\n  DOMAIN: {args.domain}")
        _safe_print(f"  Evaluations: {stats.get('count', 0)}")
        _safe_print(f"  Avg Score:   {stats.get('avg_overall', 0)}/5.0")
        _safe_print(f"  Agents:      {stats.get('agents_evaluated', 0)}")

    else:
        overview = evaluator.platform_overview()
        _safe_print("")
        _safe_print("=" * 60)
        _safe_print(f"  PLATFORM QUALITY OVERVIEW")
        _safe_print("=" * 60)
        _safe_print(f"  Total Evaluations: {overview['total_evaluations']}")
        _safe_print(f"  Platform Avg:      {overview['platform_avg']}/5.0")
        _safe_print("\n  By Domain:")
        for domain, info in sorted(overview.get("domains", {}).items()):
            _safe_print(f"    {domain:<25s} {info['count']:3d} evals  avg {info['avg']}/5")
        _safe_print("=" * 60)


def cmd_calibrate(args):
    """Calibrate LLM Judge against golden evaluation set."""
    evaluator = QualityEvaluator()
    result = evaluator.calibrate(args.golden_set)

    if "error" in result:
        _safe_print(f"Error: {result['error']}")
        return

    _safe_print("")
    _safe_print("=" * 60)
    _safe_print("  LLM JUDGE CALIBRATION REPORT")
    _safe_print("=" * 60)
    _safe_print(f"  Golden Set Size:  {result['golden_set_size']}")
    _safe_print(f"  Mean Abs Error:   {result['mae']}")
    _safe_print("\n  Dimension Bias:")
    for dname, info in sorted(result.get("dimension_bias", {}).items()):
        icon = "⚠" if info["avg_bias"] > 0.3 else "✓"
        _safe_print(f"    {icon} {dname}: {info['avg_bias']:+.2f} ({info['interpretation']})")
    _safe_print("\n  Recommendations:")
    for r in result.get("recommendations", []):
        _safe_print(f"    • {r}")
    _safe_print("=" * 60)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="QualityEvaluator — Agent Output Quality Assessment")
    sp = p.add_subparsers(dest="cmd")

    sp_eval = sp.add_parser("eval", help="Evaluate a completed task's output")
    sp_eval.add_argument("--task-id", required=True, help="Task ID to evaluate")
    sp_eval.add_argument("--agent-id", default=None, help="Agent ID (auto-detected if omitted)")

    sp_qual = sp.add_parser("quality", help="View quality reports")
    sp_qual.add_argument("--agent", default=None, help="Filter by agent name")
    sp_qual.add_argument("--domain", default=None, help="Filter by domain")
    sp_qual.add_argument("--trend", action="store_true", help="Show trend analysis")
    sp_qual.add_argument("--pass-at-k", type=int, default=0, help="Calculate pass@k metric")

    sp_cal = sp.add_parser("calibrate", help="Calibrate evaluator against golden set")
    sp_cal.add_argument("--golden-set", required=True, help="Path to golden set JSON")

    args = p.parse_args()

    if args.cmd == "eval":
        cmd_eval(args)
    elif args.cmd == "quality":
        cmd_quality(args)
    elif args.cmd == "calibrate":
        cmd_calibrate(args)
    else:
        p.print_help()
