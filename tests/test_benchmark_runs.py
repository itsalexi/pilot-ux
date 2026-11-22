import json
from pathlib import Path

import pytest

from ux_swarm import analyze, benchmark, claude, runner
from ux_swarm.config import load_study


def smoke():
    return load_study(Path(__file__).parents[1] / "examples/smoke/study.yaml")


def test_frozen_assignment_matches_shared_conditions_and_changes_only_habits(tmp_path):
    study = smoke()
    study.tasks.append(study.tasks[0].model_copy(update={"id": "second", "goal": "Follow a different goal"}))
    source = study.model_dump()
    out = tmp_path / "a"
    plan = benchmark.prepare_benchmark(study, out, panels=2, seed=4, patience=27)
    assert study.model_dump() == source
    assert plan == benchmark.prepare_benchmark(study, tmp_path / "b", panels=2, seed=4, patience=27)
    assert plan == json.loads((out / "benchmark.json").read_text())
    assert plan["model"] == "codex:gpt-6.2-astra"
    rows = plan["sessions"]
    assert len(rows) == len({r["run_id"] for r in rows}) == 16
    for pair_start in range(0, len(rows), 2):
        a, b = rows[pair_start:pair_start + 2]
        assert {a["arm"], b["arm"]} == {"generic", "persona"}
        assert all(a[key] == b[key] for key in ("task", "panel", "slot"))
    for task in study.tasks:
        for panel in (1, 2):
            block = [r for r in rows if r["panel"] == panel and r["task"] == task.id]
            assert len([r for r in block if r["arm"] == "generic"]) == 2
            assert [r["slot"] for r in block if r["singleton"]] == [1]
            assert {r["source_card"] for r in block if r["arm"] == "persona"} == {p.id for p in study.personas}
    participants = {p["id"]: p for p in plan["study"]["personas"]}
    common = [{k: v for k, v in p.items() if k not in {"id", "habits"}} for p in participants.values()]
    assert all(c == common[0] and c["patience_steps"] == 27 for c in common)
    for row in rows:
        pid, tid, repeat = row["run_id"].split("__")
        assert tid != row["task"] and repeat == "r1" and pid not in {p.id for p in study.personas}
        assert participants[pid]["habits"] == (
            study.personas[row["slot"] - 1].habits if row["arm"] == "persona" else ["Use the app as you usually would."])
    other = benchmark.prepare_benchmark(study, tmp_path / "c", panels=2, seed=7, patience=27)
    assert [(r["task"], r["slot"], r["arm"]) for r in rows] != [
        (r["task"], r["slot"], r["arm"]) for r in other["sessions"]]


def test_rejects_design_drift_and_unrelated_outputs(tmp_path):
    study = smoke()
    site = tmp_path / "site"
    site.mkdir()
    page = site / "index.html"
    page.write_text("one")
    study.target.folder = str(site)
    out = tmp_path / "benchmark"
    benchmark.prepare_benchmark(study, out)
    original = (out / "benchmark.json").read_bytes()
    for kwargs in ({"seed": 7}, {"panels": 2}, {"patience": 40}):
        with pytest.raises(ValueError, match="changed"):
            benchmark.prepare_benchmark(study, out, **kwargs)
    page.write_text("two")
    with pytest.raises(ValueError, match="build changed"):
        benchmark.prepare_benchmark(study, out)
    assert (out / "benchmark.json").read_bytes() == original
    with pytest.raises(ValueError, match="outside the served"):
        benchmark.prepare_benchmark(study, site / "private")
    unrelated = tmp_path / "other"
    unrelated.mkdir()
    (unrelated / "notes").touch()
    with pytest.raises(ValueError, match="empty benchmark"):
        benchmark.prepare_benchmark(study, unrelated)
    with runner._exclusive_output(out), pytest.raises(ValueError, match="Another runner"):
        benchmark.prepare_benchmark(study, out)


async def test_runs_plan_in_order_and_resumes_at_first_incomplete_session(tmp_path, monkeypatch):
    study = smoke()
    # Use a declared fixture revision with a fake device and no server or provider calls.
    study.target = study.target.model_copy(update={"kind": "url", "url": "https://fixture.invalid", "build_id": "v1"})
    out = tmp_path / "benchmark"
    calls, analysis = [], []
    monkeypatch.setattr(runner, "BACKOFF", [])
    plan = benchmark.prepare_benchmark(study, out, seed=9)
    order = [x["run_id"] for x in plan["sessions"]]

    async def session(study, spec, rd, url):
        assert (out / "benchmark.json").exists()
        calls.append(spec.id)
        if len(calls) == 2:
            return claude.ClaudeResult(False, "temporary failure", None)
        (rd / "outcome.json").write_text(json.dumps({"status": "done", "steps": 1}))
        (rd / "shots").mkdir()
        (rd / "shots/0000.png").write_bytes(b"fake image")
        step = {"i": 0, "tool": "done", "args": {}, "thought": "I finished", "changed": True, "shot": "shots/0000.png"}
        (rd / "steps.jsonl").write_text(json.dumps(step) + "\n")
        return claude.ClaudeResult(True, "finished", None)

    async def structured(study, role, system, prompt, schema, **kwargs):
        analysis.append(role)
        return {"canary": {"prior_knowledge": False}, "verifier": {"verdict": "verified", "reason": "done"},
                "annotator": {"findings": []}}[role]

    monkeypatch.setattr(runner, "run_session", session)
    monkeypatch.setattr(analyze.agents, "ask_json", structured)
    with pytest.raises(ValueError, match="resume the same benchmark"):
        await benchmark.run_benchmark(study, out, seed=9)
    assert calls == order[:2]
    assert "annotator" not in analysis
    assert await benchmark.run_benchmark(study, out, seed=9) == plan
    assert calls == order[:2] + order[1:]
    pooled = out / "study"
    assert not (pooled / "issues.json").exists()
    assert analysis.count("annotator") == len(order)
    lock = (pooled / "study.lock.json").read_bytes()
    observed = analysis.copy()
    await benchmark.run_benchmark(study, out, seed=9)
    assert analysis == observed and calls == order[:2] + order[1:]
    assert (pooled / "study.lock.json").read_bytes() == lock

    (pooled / "runs" / order[0] / "findings.json").write_text('{"fin')
    await benchmark.run_benchmark(study, out, seed=9)
    assert analysis == observed + ["annotator"] and calls == order[:2] + order[1:]


def _recorded_terminal_sessions(tmp_path):
    from ux_swarm.config import Study

    study = smoke()
    plan = benchmark.prepare_benchmark(study, tmp_path)
    pooled = tmp_path / "study"
    pooled.mkdir()
    runner.write_lock(Study.model_validate(plan["study"]), pooled)
    dirs = []
    for row in plan["sessions"]:
        rd = pooled / "runs" / row["run_id"]
        (rd / "shots").mkdir(parents=True)
        shot = "shots/0000.png"
        (rd / shot).write_bytes(b"recorded frame")
        step = {"i": 0, "tool": "give_up", "args": {"reason": "I'm stuck"},
                "thought": "I can't find my next step.", "changed": True, "shot": shot}
        (rd / "steps.jsonl").write_text(json.dumps(step) + "\n")
        (rd / "outcome.json").write_text(json.dumps({"status": "gave_up", "steps": 1, "contaminated": False}))
        (rd / "findings.json").write_text(json.dumps({"findings": []}))
        dirs.append(rd)
    return study, dirs


async def test_recovers_missing_and_failed_canaries_from_existing_recordings(tmp_path, monkeypatch):
    study, dirs = _recorded_terminal_sessions(tmp_path)
    first, second = (d / "outcome.json" for d in dirs[:2])
    bare = {"status": "gave_up", "steps": 1, "reason": "I'm stuck"}
    first.write_text(json.dumps(bare))  # interrupted immediately after device wrote outcome
    second.write_text(json.dumps({**bare, "backend": "codex", "seconds": 12, "model": study.codex_model,
                                  "cost_usd": 0.15, "contaminated": None, "canary_error": "provider timeout"}))
    evidence = [d.joinpath("steps.jsonl").read_bytes() for d in dirs]
    recovered = []

    async def canary(study, role, system, prompt, schema, **kwargs):
        assert role == "canary" and "I can't find my next step." in prompt
        recovered.append(role)
        if len(recovered) == 1:
            raise RuntimeError("provider unavailable")
        return {"prior_knowledge": len(recovered) == 3, "why": "assessed saved first utterance"}

    async def unexpected_participant(*args):
        pytest.fail("terminal participants must not be relaunched for a canary")

    monkeypatch.setattr(runner, "run_session", unexpected_participant)
    monkeypatch.setattr(analyze.agents, "ask_json", canary)
    with pytest.raises(ValueError, match="Resume the same benchmark.*provider unavailable"):
        await benchmark.run_benchmark(study, tmp_path)
    assert json.loads(first.read_text()) == {**bare, "contaminated": None, "canary_error": "provider unavailable"}
    await benchmark.run_benchmark(study, tmp_path)
    assert json.loads(first.read_text()) == {**bare, "contaminated": False}
    assert json.loads(second.read_text()) == {**bare, "backend": "codex", "seconds": 12, "model": study.codex_model,
                                             "cost_usd": 0.15, "contaminated": True}
    written = first.stat().st_mtime_ns
    await benchmark.run_benchmark(study, tmp_path)
    assert recovered == ["canary"] * 3 and first.stat().st_mtime_ns == written
    assert evidence == [d.joinpath("steps.jsonl").read_bytes() for d in dirs]


@pytest.mark.parametrize("corruption", ["truncated", "no utterance", "count mismatch"])
async def test_invalid_terminal_transcript_stops_before_canary_or_analysis(tmp_path, monkeypatch, corruption):
    study, dirs = _recorded_terminal_sessions(tmp_path)
    rd = dirs[0]
    tape, outcome = rd / "steps.jsonl", rd / "outcome.json"
    outcome.write_text(json.dumps({"status": "gave_up", "steps": 1}))
    if corruption == "truncated":
        tape.write_text(tape.read_text() + '{"i":')
    elif corruption == "no utterance":
        tape.write_text(json.dumps({**json.loads(tape.read_text()), "thought": "  "}))
    else:
        outcome.write_text(json.dumps({"status": "gave_up", "steps": 3}))
    before = outcome.read_bytes()

    async def unexpected(*args, **kwargs):
        pytest.fail("unreadable session evidence must not reach a provider")

    monkeypatch.setattr(analyze.agents, "ask_json", unexpected)
    monkeypatch.setattr(runner, "run_session", unexpected)
    with pytest.raises(ValueError, match="invalid transcript"):
        await benchmark.run_benchmark(study, tmp_path)
    assert outcome.read_bytes() == before
