"""Prepare and run a paired behavioral-card benchmark using the normal study engine.

benchmark.json is the private assignment key. Each pair shares the task, panel,
slot and execution conditions. Its two independent sessions run consecutively
in random order; the pair order is also randomized before any agent is started.

The device creates a fresh browser context or reinstalls the simulator app.
For apps backed by a shared account or database, the fixture owner must arrange
isolated data or a repeatable server-side reset for every attempt. A build ID
identifies the deployed code and cannot establish that its data was reset.
"""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

from . import analyze, runner
from .benchmark_review import validated_frames
from .config import Persona, Study
from .outcomes import write_outcome


def _design(study: Study, out: Path, panels: int, seed: int, patience: int) -> tuple[Study, dict]:
    if panels < 1 or not study.tasks or not study.personas:
        raise ValueError("The benchmark needs at least one task, card and panel.")
    for entries in (study.tasks, study.personas):
        if len({e.id for e in entries}) != len(entries):
            raise ValueError("Task IDs and card IDs must each be unique.")
    if not 3 <= patience <= 200:
        raise ValueError("Shared patience must be between 3 and 200.")
    if any(not p.habits or not all(h.strip() for h in p.habits) for p in study.personas):
        raise ValueError("Every treatment card needs at least one nonblank behavioral habit.")
    if len(set(study.run_backends or [])) > 1:
        raise ValueError("Choose one persona backend for both arms before preparing the benchmark.")
    if study.target.kind == "ios" and not study.target.ios_app_path:
        raise ValueError("Set target.ios_app_path to reinstall a clean simulator app between sessions.")
    if study.target.kind != "proto" and any(t.start for t in study.tasks):
        raise ValueError("Per-task start screens are supported for prototype targets only.")
    build = runner.target_build(study, out)
    if not build:
        raise ValueError("Set target.build_id to the immutable build being benchmarked.")

    rng = random.Random(seed)
    # Opaque IDs keep source card and task names out of worker paths and analysis prompts.
    tasks = [t.model_copy(update={"id": f"t{rng.getrandbits(96):024x}"}) for t in study.tasks]
    base = Persona(id="unused", name="Alex", age=35, locale=study.personas[0].locale,
                   language_register="conversational, in your own words", tech_literacy=3,
                   device="the device provided", patience_steps=patience,
                   goals=["Complete the task you were given."], fears=[], habits=["Use the app as you usually would."])
    personas, pairs = [], []
    for panel in range(1, panels + 1):
        for slot, card in enumerate(study.personas, start=1):
            ids = {}
            for arm, habits in (("generic", base.habits), ("persona", card.habits)):
                pid = f"p{rng.getrandbits(96):024x}"
                ids[arm] = pid
                personas.append(base.model_copy(update={"id": pid, "habits": habits}))
            for source, task in zip(study.tasks, tasks):
                pair = [{"run_id": f"{pid}__{task.id}__r1", "task": source.id,
                         "panel": panel, "slot": slot, "arm": arm,
                         "source_card": card.id if arm == "persona" else None,
                         "singleton": arm == "generic" and slot == 1} for arm, pid in ids.items()]
                rng.shuffle(pair)
                pairs.append(pair)
    rng.shuffle(pairs)
    sessions = [row for pair in pairs for row in pair]
    # Input repeats do not change a panel's N:N allocation. Each slot is a fresh run.
    bench = study.model_copy(update={"name": "participant-study", "personas": sorted(personas, key=lambda p: p.id),
                                     "tasks": tasks, "runs": 1, "out_dir": str(out / "study")})
    schedule = runner._model_schedule(bench)
    prompts = Path(__file__).parent / "prompts"
    manifest = {"version": 1, "seed": seed, "panels": panels, "patience": patience, "study_name": study.name,
                "tasks": {t.id: t.goal for t in study.tasks}, "sessions": sessions, "target_build": build,
                "model": schedule["persona"][0], "model_schedule": schedule, "treatment_fields": ["habits"],
                "session_timeout_seconds": runner.SESSION_TIMEOUT_S, "retry_backoff_seconds": list(runner.BACKOFF),
                "prompt_sha256": {p.stem: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(prompts.glob("*.md"))},
                "study": bench.model_dump(mode="json", exclude={"root", "out_dir", "concurrency"})}
    return bench, manifest


def _directory(study: Study, out: Path) -> Path:
    out = Path(out).resolve()
    if out == Path(study.out_dir).resolve():
        raise ValueError("Choose a benchmark output directory separate from the normal study output.")
    if study.target.kind == "static" and study.target.folder and out.is_relative_to(Path(study.target.folder).resolve()):
        raise ValueError("Keep the benchmark output outside the served static site.")
    out.mkdir(parents=True, exist_ok=True)
    return out


def _prepare(study: Study, out: Path, panels: int, seed: int, patience: int) -> tuple[Study, dict]:
    bench, manifest = _design(study, out, panels, seed, patience)
    key = out / "benchmark.json"
    if key.exists():
        if json.loads(key.read_text()) != manifest:
            raise ValueError("Benchmark design, assignment, model, prompts or build changed. Use a new benchmark directory.")
    else:
        pending = out / ".benchmark.json.partial"
        if any(p.name not in {pending.name, ".ux-swarm.lock"} for p in out.iterdir()):
            raise ValueError("Use an empty benchmark directory or one containing its original benchmark.json.")
        pending.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
        pending.replace(key)
    return bench, manifest


def prepare_benchmark(study: Study, out: Path, *, panels: int = 1, seed: int = 0, patience: int = 18) -> dict:
    """Freeze or validate the design and private assignment key without running a model."""
    out = _directory(study, out)
    with runner._exclusive_output(out):
        _, manifest = _prepare(study, out, panels, seed, patience)
        return manifest


def _recover_analysis(path: Path, key: str) -> None:
    """An interrupted analysis write is recoverable without touching session evidence."""
    if not path.exists():
        return
    try:
        value = json.loads(path.read_text())
        if isinstance(value, dict) and key in value:
            return
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass
    path.unlink()


async def _ensure_canary(study: Study, rd: Path, outcome: dict) -> None:
    if type(outcome.get("contaminated")) is bool and not outcome.get("canary_error"):
        return
    # The device writes the terminal outcome before the runner performs the canary.
    # Restore that one assessment from the recorded first utterance after an interruption.
    try:
        contaminated = await runner.check_canary(study, rd)
        if type(contaminated) is not bool:
            raise ValueError("the canary returned no boolean assessment")
    except Exception as error:
        reason = str(error)[:200] or type(error).__name__
        write_outcome(rd, {**outcome, "contaminated": None, "canary_error": reason})
        raise ValueError(f"Canary check failed for saved session {rd.name}. Resume the same benchmark "
                         f"to retry the check on its recording. Provider error: {reason}") from error
    recovered = {**outcome, "contaminated": contaminated}
    recovered.pop("canary_error", None)
    write_outcome(rd, recovered)


async def run_benchmark(study: Study, out: Path, *, panels: int = 1, seed: int = 0,
                        patience: int = 18, log=print) -> dict:
    """Collect the frozen order, verify completions and annotate individual sessions for blind review."""
    out = _directory(study, out)
    with runner._exclusive_output(out):
        bench, manifest = _prepare(study, out, panels, seed, patience)
        pooled = out / "study"
        for row in manifest["sessions"]:
            rid = row["run_id"]
            await runner.run_study(bench, pooled, only=[rid], log=log)
            rd = pooled / "runs" / rid
            outcome = analyze.load_json(rd / "outcome.json") or {}
            if outcome.get("status") not in runner.FINAL | {"abandoned"}:
                raise ValueError(f"Session {rid} has no terminal outcome. Check its device/agent log and resume the same benchmark.")
            try:
                validated_frames(rd, outcome)
            except ValueError as error:
                raise ValueError(f"Terminal session {rid} has an invalid transcript ({error}). Preserve the "
                                 "collection and use a fresh benchmark directory if the evidence is incomplete.") from error
            await _ensure_canary(bench, rd, outcome)
            if outcome["status"] == "done":
                _recover_analysis(rd / "verdict.json", "verdict")
            _recover_analysis(rd / "findings.json", "findings")
        await analyze.verify(bench, pooled, log=log)
        await analyze.annotate(bench, pooled, log=log)
        return manifest
