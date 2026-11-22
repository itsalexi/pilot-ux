"""Recheck an issue against independently recorded sessions from a repaired build."""
from __future__ import annotations

import json
import re
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from .analyze import run_dirs
from .config import Study
from .runner import RunSpec


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    issue: str
    before_run: str
    before_step: int = Field(strict=True, ge=0)
    after_run: str
    after_step: int = Field(strict=True, ge=0)
    result: Literal["improved", "recurred", "inconclusive"]
    note: str = Field(min_length=1)


class Witness(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    before_version: str = Field(min_length=1)
    after_version: str = Field(min_length=1)
    reviewer: str = Field(default="reviewer (unspecified)", min_length=1)
    observations: list[Observation] = Field(min_length=1)


@dataclass
class Session:
    spec: RunSpec
    directory: Path
    model: tuple[str, str]
    steps: dict[int, dict]
    started: float
    ended: float
    status: str

    def require_shot(self, step: int):
        record = self.steps.get(step)
        rel = (record or {}).get("shot")
        path = (self.directory / rel).resolve() if rel else None
        if not path or not path.is_relative_to(self.directory) or not path.is_file():
            raise ValueError(f"{self.spec.id}: no recorded screenshot for step {step}")
        with Image.open(path) as frame:
            frame.verify()


def read_json(path: Path):
    return json.loads(path.read_text())


def sessions(study: Study, out: Path) -> dict[str, Session]:
    recorded = {}
    for spec, rd in run_dirs(study, out):
        outcome = read_json(rd / "outcome.json")
        if outcome.get("status") not in {"done", "gave_up", "out_of_patience"} or outcome.get("contaminated"):
            continue
        model = outcome.get("model")
        if not model:
            continue
        backend = outcome.get("backend") or study.backend_for("persona", spec.n)
        path = rd / "steps.jsonl"
        if not path.is_file():
            continue
        steps = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        stamps = [row.get("ts") for row in steps]
        if not stamps or not all(isinstance(t, (float, int)) for t in stamps):
            continue
        status = outcome["status"]
        if status == "done":
            verdict = rd / "verdict.json"
            status = read_json(verdict)["verdict"] if verdict.is_file() else "claim awaiting verification"
        recorded[spec.id] = Session(spec, rd, (backend, model), {s["i"]: s for s in steps},
                                    min(stamps), max(stamps), status)
    return recorded


def candidates(title: str, later_issues: list[dict], comparable: set[str]) -> list[dict]:
    # Issue IDs are allocated anew at every merge. Titles only suggest where to inspect.
    stop = {"the", "to", "on", "is", "does", "not", "a", "an", "in", "of", "and", "for", "after"}
    words = lambda s: set(re.findall(r"\w+", s.casefold())) - stop
    baseline = words(title)
    ranked = []
    for issue in later_issues:
        if not comparable.intersection(issue["runs"]):
            continue
        other = words(issue["title"])
        overlap = baseline & other
        score = len(overlap) / max(1, len(baseline | other))
        if (len(overlap) >= 2 and score >= 0.25) or title.casefold() == issue["title"].casefold():
            ranked.append((score, {"id": issue["id"], "title": issue["title"]}))
    return [issue for _, issue in sorted(ranked, key=lambda pair: -pair[0])[:3]]


def compare(before: Path, after: Path, witness: Witness | None = None) -> dict:
    before, after = before.resolve(), after.resolve()
    if before == after:
        raise ValueError("the repaired build needs its own newly recorded output directory")
    old_lock, new_lock = (read_json(p / "study.lock.json") for p in (before, after))
    old, new = (Study.model_validate(lock["study"]) for lock in (old_lock, new_lock))
    for role in ("annotator", "merger", "verifier"):
        old_model, new_model = (lock.get("models", {}).get(role) for lock in (old_lock, new_lock))
        if not old_model or old_model != new_model:
            raise ValueError(f"{role} model differs or is unrecorded in the study locks")
    device_fields = ("kind", "fidelity", "viewport", "scale", "mobile")
    if old.product_hint != new.product_hint or any(
        getattr(old.target, field) != getattr(new.target, field) for field in device_fields
    ):
        raise ValueError("target kind, fidelity, viewport, device settings and product hint must match")

    earlier, later = sessions(old, before), sessions(new, after)
    last_before = max((s.ended for s in earlier.values()), default=0)
    matches = {bid: {aid for aid, a in later.items()
                     if a.started > last_before and b.model == a.model
                     and b.spec.task == a.spec.task and b.spec.persona == a.spec.persona}
               for bid, b in earlier.items()}
    comparable = set().union(*matches.values())
    if not comparable:
        raise ValueError("no fresh comparable sessions: check timestamps, persona, task, criteria and recorded model")
    old_issues, new_issues = (read_json(p / "issues.json") for p in (before, after))
    issue_rows = {}
    for issue in old_issues:
        comparable_for_issue = set().union(*(matches.get(r, set()) for r in issue["runs"]))
        issue_rows[issue["id"]] = {"id": issue["id"], "title": issue["title"], "status": "inconclusive",
                                   "after_runs": sorted(comparable_for_issue),
                                   "candidates": candidates(issue["title"], new_issues, comparable_for_issue),
                                   "observations": []}

    if witness:
        if witness.before_version == witness.after_version:
            raise ValueError("identify the distinct before and after versions or variants")
        for obs in witness.observations:
            original = next((i for i in old_issues if i["id"] == obs.issue), None)
            if not original or not any(ev["run"] == obs.before_run and obs.before_step in ev["steps"]
                                       for ev in original["evidence"]):
                raise ValueError(f"{obs.issue}: before_run and before_step must cite evidence for that original issue")
            if obs.after_run not in matches.get(obs.before_run, set()):
                raise ValueError(f"{obs.issue}: the witnessed sessions are not a fresh matched persona/task/model pair")
            earlier[obs.before_run].require_shot(obs.before_step)
            later[obs.after_run].require_shot(obs.after_step)
            issue_rows[obs.issue]["observations"].append({**obs.model_dump(exclude={"issue"}), "reviewer": witness.reviewer})
        for row in issue_rows.values():
            results = {o["result"] for o in row["observations"]} - {"inconclusive"}
            if len(results) > 1:
                row["status"] = "mixed observations"
            elif results:
                row["status"] = "improvement witnessed" if "improved" in results else "recurrence witnessed"

    task_outcomes = {}
    for phase, group in (("before", [s for bid, s in earlier.items() if matches[bid]]),
                         ("after", [later[aid] for aid in sorted(comparable)])):
        for session in group:
            counts = task_outcomes.setdefault(session.spec.task.id, {}).setdefault(phase, Counter())
            counts[session.status] += 1
    return {"before_dir": str(before), "after_dir": str(after), "before_version": witness.before_version if witness else None,
            "after_version": witness.after_version if witness else None, "comparable_sessions": len(comparable),
            "task_outcomes": task_outcomes, "issues": list(issue_rows.values())}


def recheck(before: Path, after: Path, witness_path: Path | None = None) -> str:
    from .report import build

    output = after / "recheck.json"
    if witness_path is None and output.is_file():
        previous = read_json(output)
        if any(row.get("observations") for row in previous.get("issues", [])):
            raise ValueError("this comparison already contains observations; supply --witness to replace them")
    witness = Witness.model_validate(yaml.safe_load(witness_path.read_text())) if witness_path else None
    result = compare(before, after, witness)
    # Keep a prior, readable comparison intact if a write is interrupted.
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(dir=after, prefix=".recheck-", mode="w", encoding="utf-8", delete=False) as temp:
            tmp = Path(temp.name)
            json.dump(result, temp, ensure_ascii=False, indent=2)
            temp.write("\n")
        tmp.replace(output)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
    study = Study.model_validate(read_json(after / "study.lock.json")["study"])
    _, html = build(study, after)
    lines = ["# Repair recheck", "", f"{result['comparable_sessions']} fresh matched sessions. "
             "Each witnessed result describes the cited observation. An absent finding is inconclusive.", ""]
    for task, counts in result["task_outcomes"].items():
        outcomes = [" / ".join(f"{n} {status}" for status, n in counts[phase].items()) for phase in ("before", "after")]
        lines.append(f"- {task}: {outcomes[0]} before → {outcomes[1]} after")
    lines.append("")
    for issue in result["issues"]:
        suggested = ", ".join(c["id"] for c in issue["candidates"])
        suffix = f" (possible matches to inspect: {suggested})" if suggested else ""
        lines.append(f"- {issue['id']} · {issue['title']}: {issue['status']}{suffix}")
    return "\n".join(lines + ["", f"Report: {html}"])
