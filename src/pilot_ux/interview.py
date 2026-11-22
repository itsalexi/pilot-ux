"""Post-task interview in character, then SSR scoring of the free-text answers."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from . import agents, embedders, ssr
from .config import Study
from .prompts import render
from .runner import plan_runs, product_hint

CLOSE_Q = "What would make you close this app and not come back?"
NAIVE = ["ease", "trust", "use_intent", "pay_intent"]


def questions() -> list[tuple[str, str]]:
    qs = [(c, ssr.anchor_sets(c)[0]) for c in ssr.constructs()]
    return qs + [("close_trigger", CLOSE_Q)]


def interview_schema() -> dict:
    ans = {k: {"type": "string"} for k, _ in questions()}
    naive = {k: {"type": "integer", "minimum": 1, "maximum": 5} for k in NAIVE}
    return {"type": "object", "required": ["answers", "naive"], "properties": {
        "answers": {"type": "object", "properties": ans, "required": list(ans)},
        "naive": {"type": "object", "properties": naive, "required": NAIVE,
                  "description": "AFTER answering in words: rate each 1 (worst) to 5 (best) as a number."}}}


def ending_text(outcome: dict) -> str:
    st = outcome.get("status")
    if st == "done":
        return f"You felt you were done: {outcome.get('summary', '')}"
    if st == "gave_up":
        return f"You gave up: {outcome.get('reason', '')}"
    if st == "out_of_patience":
        return "You ran out of patience and closed the app."
    return "You stopped partway."


def transcript_log(run_dir: Path) -> str:
    lines = []
    for raw in (run_dir / "steps.jsonl").read_text().splitlines():
        s = json.loads(raw)
        lines.append(f"{s['i']}. {s['thought']}")
    return "\n".join(lines)


async def interview_run(study: Study, spec, run_dir: Path) -> None:
    outcome = json.loads((run_dir / "outcome.json").read_text())
    shots = sorted((run_dir / "shots").glob("*.png"))[-3:]
    files = {f"last_screens/{p.name}": p for p in shots}
    qtext = "\n".join(f"- {k}: {q}" for k, q in questions())
    prompt = render("interview", card=spec.persona.card(), product_hint=product_hint(study), goal=spec.task.goal,
                    log=transcript_log(run_dir), ending=ending_text(outcome), questions=qtext)
    prompt += "\nThe last screens are in the folder last_screens/ (use Read to look at them)."
    res = await agents.ask_json(study, "interview", f"You are {spec.persona.name}. Stay in character.",
                                prompt, interview_schema(), files=files, run=spec.n)
    (run_dir / "interview.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))


def score_run(run_dir: Path, embedder) -> dict:
    iv = json.loads((run_dir / "interview.json").read_text())
    scores = {c: ssr.score(iv["answers"][c], c, embedder) for c in ssr.constructs() if iv["answers"].get(c)}
    sus_items = [scores[f"sus_{i}"]["pmf"] for i in range(1, 11) if f"sus_{i}" in scores]
    out = {"scores": scores, "naive": iv.get("naive", {}), "embedder": embedder.spec}
    if len(sus_items) == 10:
        out["sus"] = ssr.sus_distribution(sus_items)
    (run_dir / "ssr.json").write_text(json.dumps(out, indent=1))
    return out


async def run_interviews(study: Study, out: Path, log=print) -> None:
    sem = asyncio.Semaphore(study.concurrency)
    emb = embedders.get(study.embedder)

    async def one(spec):
        rd = out / "runs" / spec.id
        if not (rd / "steps.jsonl").exists() or not (rd / "outcome.json").exists():
            return
        if not (rd / "interview.json").exists():
            async with sem:
                try:
                    await interview_run(study, spec, rd)
                except Exception as e:
                    log(f"  interview {spec.id} failed: {e}")
                    return
        if not (rd / "ssr.json").exists():
            score_run(rd, emb)
        log(f"  interviewed {spec.id}")

    await asyncio.gather(*(one(s) for s in plan_runs(study)))
