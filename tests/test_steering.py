import asyncio

import pytest

from pilot_ux import claude, runner
from pilot_ux.config import load_study


@pytest.fixture
def study(tmp_path):
    config = tmp_path / "study.yaml"
    config.write_text(
        "name: steering\n"
        "target: {kind: url, url: 'http://example.test/', build_id: test-build}\n"
        "tasks: [{id: setup, goal: Set it up, success_criteria: [Ready]}]\n"
        "personas: [{ref: default/older-non-techy}]\n"
        "runs: 4\nconcurrency: 2\nbackend: codex\ncodex_model: pinned\n"
    )
    return load_study(config)


async def test_live_drain_finishes_active_sessions_and_preserves_pending_work(study, tmp_path, monkeypatch):
    out = tmp_path / "runs"
    two_started, finish = asyncio.Event(), asyncio.Event()
    starts = []

    async def session(study, spec, directory, url):
        starts.append(spec.n)
        if len(starts) == 2:
            two_started.set()
        await finish.wait()
        (directory / "outcome.json").write_text('{"status": "done"}')
        return claude.ClaudeResult(True, "", None)

    monkeypatch.setattr(runner, "run_session", session)
    run = asyncio.create_task(runner.run_study(study, out))
    try:
        await asyncio.wait_for(two_started.wait(), timeout=5)
        lock = out / "study.lock.json"
        original_lock = lock.read_bytes()
        pending_dir = out / "runs" / runner.plan_runs(study)[2].id
        pending_dir.mkdir()
        partial = pending_dir / "device.log"
        partial.write_text("earlier interrupted attempt")
        runner.request_drain(out)
        runner.request_drain(out)
    finally:
        finish.set()
        completed = await run

    assert completed is False
    assert starts == [1, 2]
    assert partial.read_text() == "earlier interrupted attempt"
    assert not (out / "runs" / runner.plan_runs(study)[3].id).exists()
    terminal = out / "runs" / runner.plan_runs(study)[0].id / "outcome.json"
    original_outcome = terminal.read_bytes()

    assert await runner.run_study(study, out) is False
    assert await runner.run_study(study, out, only=["__r1", "__r2"]) is True
    assert starts == [1, 2]
    runner.clear_drain(out)
    runner.clear_drain(out)
    assert await runner.run_study(study, out) is True
    assert starts == [1, 2, 3, 4]
    assert terminal.read_bytes() == original_outcome
    assert lock.read_bytes() == original_lock


async def test_drain_before_launch_skips_target_but_validates_resume(study, tmp_path, monkeypatch):
    out = tmp_path / "runs"
    runner.request_drain(out)
    monkeypatch.setattr(runner.TargetHost, "__enter__", lambda self: pytest.fail("started held target"))
    assert await runner.run_study(study, out) is False
    assert not (out / "runs").exists()

    study.tasks[0].goal = "Changed during hold"
    with pytest.raises(ValueError, match="study settings changed"):
        await runner.run_study(study, out)


async def test_drain_during_last_participant_does_not_report_unstarted_work(study, tmp_path, monkeypatch):
    out = tmp_path / "runs"

    async def last_session(study, spec, directory, url):
        runner.request_drain(out)
        (directory / "outcome.json").write_text('{"status": "done"}')
        return claude.ClaudeResult(True, "", None)

    monkeypatch.setattr(runner, "run_session", last_session)
    assert await runner.run_study(study, out, only=["__r1"]) is True
    assert await runner.run_study(study, out) is False
