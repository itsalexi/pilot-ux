"""Blind verification, annotation and merging of persona sessions."""
from __future__ import annotations

import asyncio
import json
import statistics
from pathlib import Path

from PIL import Image

from . import agents, claude
from .benchmark_review import validated_frames
from .config import Study, Task
from .outcomes import write_json
from .prompts import render
from .runner import plan_runs

VERDICT_SCHEMA = {"type": "object", "required": ["verdict", "reason"], "properties": {
    "verdict": {"type": "string", "enum": ["verified", "not_verified", "unclear"]}, "reason": {"type": "string"}}}

FINDING = {"type": "object", "required": ["screen", "element", "description", "severity", "steps", "evidence_quote",
                                          "suggested_fix", "is_prototype_gap", "agent_misread", "category"],
           "properties": {
               "screen": {"type": "string", "description": "what the screen is, in plain words"},
               "element": {"type": "string"},
               "description": {"type": "string"},
               "severity": {"type": "integer", "minimum": 0, "maximum": 4},
               "steps": {"type": "array", "items": {"type": "integer"}},
               "evidence_quote": {"type": "string"},
               "suggested_fix": {"type": "string"},
               "is_prototype_gap": {"type": "boolean"},
               "agent_misread": {"type": "boolean"},
               "category": {"type": "string", "enum": ["navigation", "labels-copy", "feedback", "affordance",
                                                       "trust-safety", "data-entry", "money-math", "layout-visual",
                                                       "flow-structure", "other"]}}}
FINDINGS_SCHEMA = {"type": "object", "required": ["findings"],
                   "properties": {"findings": {"type": "array", "items": FINDING}}}
MERGE_SCHEMA = {"type": "object", "required": ["issues"], "properties": {"issues": {"type": "array", "items": {
    "type": "object", "required": ["title", "description", "suggested_fix", "members"],
    "properties": {"title": {"type": "string"}, "description": {"type": "string"},
                   "suggested_fix": {"type": "string"}, "members": {"type": "array", "items": {"type": "string"}}}}}}}


def run_dirs(study: Study, out: Path):
    for spec in plan_runs(study):
        rd = out / "runs" / spec.id
        if (rd / "outcome.json").exists():
            yield spec, rd


def effective_status(outcome: dict, verdict: dict | None) -> str:
    st = outcome.get("status", "error")
    if st == "done":
        return "success" if verdict and verdict.get("verdict") == "verified" else "failed_claim"
    return st


def load_json(p: Path):
    return json.loads(p.read_text()) if p.exists() else None


async def _judge_screens(study: Study, task: Task, files: dict[str, Path]) -> dict:
    prompt = render("verifier", goal=task.goal, criteria="\n".join(f"- {c}" for c in task.success_criteria),
                    files=", ".join(files))
    if task.verify_after == "reopen":
        prompt += "\nThe attached image is the first screen captured when the participant reopened the app."
    return await agents.ask_json(study, "verifier", "You are a strict, careful test verifier.",
                                 prompt, VERDICT_SCHEMA, files=files)


async def _verify_reopened(study: Study, task: Task, rd: Path, outcome: dict) -> dict:
    try:
        frames = validated_frames(rd, outcome)
        step = next((i for i in reversed(frames) if frames[i]["tool"] == "reopen"), None)
        if step is None:
            return {"verdict": "not_verified", "reason": "The completed recording contains no reopen action."}
        expected = f"shots/{step:04d}.png"
        if frames[step]["shot"] != expected:
            raise ValueError("the reopen action references a different frame")
        shot = rd / expected
        with Image.open(shot) as frame:
            if frame.format != "PNG":
                raise ValueError("expected a PNG recording")
            frame.verify()
    except (OSError, ValueError, SyntaxError) as error:
        return {"verdict": "unclear", "reason": f"Could not read the reopen evidence ({error}).",
                "evidence_error": True}
    verdict = await _judge_screens(study, task, {"reopened.png": shot})
    return {**verdict, "evidence_step": step}


async def verify(study: Study, out: Path, log=print) -> None:
    sem = asyncio.Semaphore(study.concurrency)

    async def one(spec, rd):
        outcome = load_json(rd / "outcome.json")
        if outcome.get("status") != "done":
            return
        path = rd / "verdict.json"
        prior = load_json(path)
        if prior and prior.get("verify_after") == spec.task.verify_after and not prior.get("evidence_error"):
            return
        async with sem:
            if spec.task.verify_after == "reopen":
                v = await _verify_reopened(study, spec.task, rd, outcome)
                v["verify_after"] = "reopen"
            else:
                shots = sorted((rd / "shots").glob("*.png"))[-3:]
                v = await _judge_screens(study, spec.task, {f"final/{i + 1}.png": p for i, p in enumerate(shots)})
        write_json(path, v)
        log(f"  verified {spec.id}: {v['verdict']}")

    await asyncio.gather(*(one(s, rd) for s, rd in run_dirs(study, out)))


def transcript_md(rd: Path) -> str:
    lines = ["| step | P says (thinking aloud) | action | screen changed | screenshot after |", "|---|---|---|---|---|"]
    for raw in (rd / "steps.jsonl").read_text().splitlines():
        s = json.loads(raw)
        act = s["tool"] + (f" {json.dumps(s['args'], ensure_ascii=False)}" if s["args"] else "")
        thought = s["thought"].replace("|", "/").replace("\n", " ")
        lines.append(f"| {s['i']} | {thought} | {act} | {'yes' if s['changed'] else 'NO'} | {s['shot']} |")
    return "\n".join(lines)


def gaps_md(rd: Path) -> str:
    p = rd / "gaps.jsonl"
    if not p.exists():
        return "(none)"
    return "\n".join(f"- tap at ({g['x']}, {g['y']}) on an unbuilt part of the prototype"
                     for g in map(json.loads, p.read_text().splitlines())) or "(none)"


async def annotate(study: Study, out: Path, log=print) -> None:
    sem = asyncio.Semaphore(study.concurrency)
    from .interview import ending_text
    import tempfile

    async def one(spec, rd):
        if (rd / "findings.json").exists() or not (rd / "steps.jsonl").exists():
            return
        outcome = load_json(rd / "outcome.json")
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "transcript.md").write_text(transcript_md(rd))
            (Path(d) / "gaps.md").write_text(gaps_md(rd))
            files = {"transcript.md": Path(d) / "transcript.md", "gaps.md": Path(d) / "gaps.md", **annotator_shots(rd)}
            prompt = render("annotator", goal=spec.task.goal, ending=ending_text(outcome).replace("You", "P"),
                            fidelity=study.target.fidelity)
            async with sem:
                f = await agents.ask_json(study, "annotator", "You are a senior usability researcher.",
                                          prompt, FINDINGS_SCHEMA, files=files)
        (rd / "findings.json").write_text(json.dumps(f, indent=1, ensure_ascii=False))
        log(f"  annotated {spec.id}: {len(f['findings'])} findings")

    await asyncio.gather(*(one(s, rd) for s, rd in run_dirs(study, out)))


ANNOTATOR_SHOTS = 24


def annotator_shots(rd: Path, cap: int = ANNOTATOR_SHOTS) -> dict[str, Path]:
    """Screens sent to the annotator: all of them up to `cap`; past that, the first two, the last eight
    (where testers stall and quit) and an even spread of the middle. Names keep their step numbers."""
    shots = sorted((rd / "shots").glob("*.png"))
    if len(shots) > cap:
        head, tail = shots[:2], shots[-8:]
        middle = shots[2:-8]
        k = cap - len(head) - len(tail)
        picked = [middle[round(i * (len(middle) - 1) / max(k - 1, 1))] for i in range(k)] if k > 0 else []
        shots = head + sorted(set(picked)) + tail
    return {f"shots/{s.name}": s for s in shots}


def collect_findings(study: Study, out: Path) -> list[dict]:
    allf, n = [], 0
    for spec, rd in run_dirs(study, out):
        data = load_json(rd / "findings.json")
        for f in (data or {}).get("findings", []):
            n += 1
            allf.append({**f, "id": f"F{n}", "run": spec.id, "persona": spec.persona.id, "task": spec.task.id})
    return allf


async def merge(study: Study, out: Path, log=print) -> list[dict]:
    findings = collect_findings(study, out)
    by_id = {f["id"]: f for f in findings}
    groups: list[dict] = []
    if findings:
        slim = [{"id": f["id"], "task": f["task"], "screen": f["screen"], "element": f["element"],
                 "description": f["description"], "severity": f["severity"],
                 "prototype_gap": f["is_prototype_gap"]} for f in findings]
        res = await agents.ask_json(study, "merger", "You are a meticulous usability researcher.",
                                    render("merger", findings=json.dumps(slim, ensure_ascii=False)), MERGE_SCHEMA)
        seen = set()
        for g in res["issues"]:
            members = [m for m in g["members"] if m in by_id and m not in seen]
            seen.update(members)
            if members:
                groups.append({**g, "members": members})
        for f in findings:  # never silently drop a finding the merger forgot
            if f["id"] not in seen:
                groups.append({"title": f"{f['screen']}: {f['element']}", "description": f["description"],
                               "suggested_fix": f["suggested_fix"], "members": [f["id"]]})
    n_personas = len(study.personas)
    issues = []
    for i, g in enumerate(groups, 1):
        mem = [by_id[m] for m in g["members"]]
        personas = sorted({m["persona"] for m in mem})
        gap_votes = sum(m["is_prototype_gap"] for m in mem)
        misread = sum(m["agent_misread"] for m in mem)
        issues.append({
            "id": f"I{i}", "title": g["title"], "description": g["description"], "suggested_fix": g["suggested_fix"],
            "severity": float(statistics.median(m["severity"] for m in mem)),
            "personas": personas, "runs": sorted({m["run"] for m in mem}), "tasks": sorted({m["task"] for m in mem}),
            "frequency": len(personas) / n_personas,
            "prototype_gap": gap_votes * 2 > len(mem), "agent_misread_share": misread / len(mem),
            "category": statistics.mode(m["category"] for m in mem),
            "evidence": [{"run": m["run"], "steps": m["steps"], "quote": m["evidence_quote"], "finding": m["id"]}
                         for m in mem]})
    issues.sort(key=lambda x: (x["prototype_gap"], -x["severity"] * x["frequency"], -x["severity"]))
    (out / "issues.json").write_text(json.dumps(issues, indent=1, ensure_ascii=False))
    log(f"  merged {len(findings)} findings into {len(issues)} issues")
    return issues


def agreement(study: Study, out: Path) -> dict:
    from .stats import run_agreement
    issues = load_json(out / "issues.json") or []
    hit: dict[str, set] = {}
    for iss in issues:
        if iss["prototype_gap"] or iss["severity"] < 1:
            continue
        for r in iss["runs"]:
            hit.setdefault(r, set()).add(iss["id"])
    cells: dict[str, dict] = {}
    for spec, rd in run_dirs(study, out):
        st = effective_status(load_json(rd / "outcome.json"), load_json(rd / "verdict.json"))
        cells.setdefault(f"{spec.persona.id}__{spec.task.id}", {})[spec.id] = (hit.get(spec.id, set()), st)
    return run_agreement(cells)
