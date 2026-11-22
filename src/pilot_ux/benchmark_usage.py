"""Measured usage of the saved participant attempts in a frozen benchmark."""
from __future__ import annotations

import json
import math
from pathlib import Path

from .device_mcp import TOOL_NAMES

_UI_ACTIONS = {"tap", "type_text", "scroll", "back", "reopen"}
_TOKENS = ("input_tokens", "cached_input_tokens", "output_tokens")
_METRICS = ("device_calls", "ui_actions", "elapsed_seconds", *("codex_" + name for name in _TOKENS),
            "provider_cost_usd")


def _count(value):
    return value if type(value) is int and value >= 0 else None


def _amount(value):
    if type(value) is int:
        return _count(value)
    return value if type(value) is float and value >= 0 and math.isfinite(value) else None


def _events(path: Path):
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError("expected a JSON object")
            yield record


def _device_counts(directory, outcome):
    expected = _count(outcome.get("steps"))
    if expected is None:
        return None, None
    calls = actions = 0
    try:
        for step in _events(directory / "steps.jsonl"):
            tool = step.get("tool")
            if _count(step.get("i")) != calls or tool not in TOOL_NAMES:
                return None, None
            calls += 1
            actions += tool in _UI_ACTIONS
    except (OSError, ValueError):
        return None, None
    return (calls, actions) if calls == expected else (None, None)


def _provider_usage(directory, outcome, row):
    backend = outcome.get("backend")
    # Claude's wrapper defaults an absent price to zero. Only a positive stored
    # price proves a measurement when its raw result is missing.
    cost = _amount(outcome.get("cost_usd"))
    if backend == "claude" and cost is not None and cost > 0:
        row["provider_cost_usd"] = cost
    terminal = []
    unfinished = False
    try:
        for event in _events(directory / "agent.jsonl"):
            kind = event.get("type")
            if kind in ("turn.started", "turn.failed", "error"):
                unfinished = True
            elif kind in ("turn.completed", "result"):
                unfinished = False
                terminal.append(event)
    except (OSError, ValueError):
        return
    # The runner launches a single CLI turn per attempt. A truncated or
    # ambiguous event stream cannot establish a whole-attempt token total.
    if unfinished or len(terminal) != 1:
        return
    event = terminal[0]
    if event["type"] == "result" and backend in (None, "claude"):
        row["provider_cost_usd"] = _amount(event.get("total_cost_usd"))
    if event["type"] == "turn.completed" and backend in (None, "codex"):
        usage = event.get("usage")
        if isinstance(usage, dict):
            for name in _TOKENS:
                row["codex_" + name] = _count(usage.get(name))


def summarize_usage(benchmark_dir: Path) -> dict:
    """Arm totals require a measurement from every scheduled session in that arm."""
    benchmark_dir = Path(benchmark_dir)
    manifest = json.loads((benchmark_dir / "benchmark.json").read_text(encoding="utf-8"))
    sessions = []
    root = (benchmark_dir / "study" / "runs").resolve()
    for spec in manifest["sessions"]:
        run_id = spec["run_id"]
        directory = (root / run_id).resolve()
        if directory.parent != root or Path(run_id).name != run_id:
            raise ValueError(f"invalid benchmark run ID: {run_id}")
        row = {k: spec[k] for k in ("run_id", "task", "panel", "arm", "slot", "singleton") if k in spec}
        row.update(dict.fromkeys(_METRICS))
        sessions.append(row)
        try:
            outcome = json.loads((directory / "outcome.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(outcome, dict) or outcome.get("status") not in (
            "done", "gave_up", "out_of_patience", "abandoned", "error"
        ):
            continue
        row["device_calls"], row["ui_actions"] = _device_counts(directory, outcome)
        row["elapsed_seconds"] = _amount(outcome.get("seconds"))
        _provider_usage(directory, outcome, row)

    arms = {}
    for arm in sorted({row["arm"] for row in sessions}):
        rows = [row for row in sessions if row["arm"] == arm]
        coverage = {metric: sum(r[metric] is not None for r in rows) for metric in _METRICS}
        arms[arm] = {"planned_sessions": len(rows), "measured_sessions": coverage,
                     **{metric: sum(r[metric] for r in rows) if coverage[metric] == len(rows) else None
                        for metric in _METRICS}}
    return {"scope": "Retained participant attempts with recorded outcomes. Device calls include look and "
                     "terminal actions. UI actions count taps, typing, scrolling, back and reopen. Costs reflect "
                     "provider-reported CLI estimates. Earlier retries, analysis roles and embeddings are unmeasured.",
            "study_cost_usd": None, "sessions": sessions, "arms": arms}
