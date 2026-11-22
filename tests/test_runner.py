import asyncio
import json

import pytest

from ux_swarm import claude, runner
from ux_swarm.config import load_study


@pytest.mark.parametrize("response", [{}, {"prior_knowledge": None}, {"prior_knowledge": "false"},
                                      {"prior_knowledge": 0}, {"prior_knowledge": False}, {"prior_knowledge": True}])
async def test_canary_requires_an_explicit_boolean(tmp_path, monkeypatch, response):
    study = _study(tmp_path, personas=1, tasks=1)
    (tmp_path / "steps.jsonl").write_text(json.dumps({"i": 0, "thought": "I have never seen it."}) + "\n")

    async def assess(*args):
        return response

    monkeypatch.setattr(runner.agents, "ask_json", assess)
    if type(response.get("prior_knowledge")) is bool:
        assert await runner.check_canary(study, tmp_path) is response["prior_knowledge"]
    else:
        with pytest.raises(ValueError, match="boolean prior_knowledge"):
            await runner.check_canary(study, tmp_path)


@pytest.mark.parametrize("transcript", [None, "", '{"i":0,"thought":"  "}'])
async def test_canary_needs_a_first_observation(tmp_path, monkeypatch, transcript):
    study = _study(tmp_path, personas=1, tasks=1)
    if transcript is not None:
        (tmp_path / "steps.jsonl").write_text(transcript)
    monkeypatch.setattr(runner.agents, "ask_json", lambda *args: pytest.fail("no observation to assess"))
    with pytest.raises(ValueError, match="without a first"):
        await runner.check_canary(study, tmp_path)


def test_build_cmd_isolation_flags(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cmd = claude.build_cmd("claude-opus-5-5", "SYS", "USER", mcp_config=tmp_path / "m.json",
                           allowed=["mcp__device"])
    joined = " ".join(cmd)
    assert cmd[:2] == ["claude", "-p"]
    assert cmd[cmd.index("--setting-sources") + 1] == ""
    assert cmd[cmd.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in cmd
    assert cmd[cmd.index("--model") + 1] == "claude-opus-5-5"
    assert cmd[cmd.index("--system-prompt") + 1] == "SYS"
    assert cmd[cmd.index("--allowedTools") + 1] == "mcp__device"
    assert "--bare" not in cmd and "--no-session-persistence" in joined
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert "--bare" in claude.build_cmd("m", "s", "u", mcp_config=None)


def _study(tmp_path, personas=2, tasks=2):
    ps = "\n".join(f"  - ref: default/{p}" for p in ["older-non-techy", "detail-checker"][:personas])
    ts = "\n".join(f"  - {{id: t{i}, goal: g{i}, success_criteria: [c]}}" for i in range(tasks))
    p = tmp_path / "study.yaml"
    p.write_text(f"name: s\ntarget: {{kind: url, url: 'http://x'}}\ntasks:\n{ts}\npersonas:\n{ps}\n")
    return load_study(p)


def test_plan_runs_count(tmp_path):
    specs = runner.plan_runs(_study(tmp_path))
    assert len(specs) == 12
    assert len({s.id for s in specs}) == 12
    assert specs[0].id == "older-non-techy__t0__r1"


async def test_resume_skips_finished_and_retries_errors(tmp_path, monkeypatch):
    study = _study(tmp_path, personas=1, tasks=1)
    study.runs = 2
    out = tmp_path / "out"
    out.mkdir()
    runner.write_lock(study, out)
    done_dir = out / "runs" / "older-non-techy__t0__r1"
    done_dir.mkdir(parents=True)
    (done_dir / "outcome.json").write_text(json.dumps({"status": "done", "steps": 3}))
    calls = []

    async def fake_session(study, spec, run_dir, url):
        calls.append(spec.id)
        if len(calls) == 1:
            return claude.ClaudeResult(ok=False, text="rate limited", structured=None, usage={}, cost_usd=0)
        (run_dir / "outcome.json").write_text(json.dumps({"status": "gave_up", "steps": 2}))
        return claude.ClaudeResult(ok=True, text="", structured=None, usage={}, cost_usd=0.1)

    monkeypatch.setattr(runner, "run_session", fake_session)
    monkeypatch.setattr(runner, "BACKOFF", [0, 0])
    monkeypatch.setattr(runner, "check_canary", lambda *a, **k: _async(False))
    await runner.run_study(study, out)
    assert calls == ["older-non-techy__t0__r2", "older-non-techy__t0__r2"]
    o = json.loads((out / "runs/older-non-techy__t0__r2/outcome.json").read_text())
    assert o["status"] == "gave_up" and o["contaminated"] is False
    assert (out / "study.lock.json").exists()


async def _async(v):
    return v


def test_resume_preserves_original_lock_and_ignores_operational_changes(tmp_path):
    study = _study(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    runner.write_lock(study, out)
    original = (out / "study.lock.json").read_bytes()
    study.concurrency += 3
    study.codex_model = "unused-codex-model"
    selected = runner.plan_runs(study)[-1:]
    assert runner.write_lock(study, out, selected) == selected
    assert (out / "study.lock.json").read_bytes() == original


@pytest.mark.parametrize("change", ["goal", "persona", "model", "build"])
async def test_resume_refuses_changed_conditions_before_mutating_artifacts(tmp_path, change):
    study = _study(tmp_path, personas=1, tasks=1)
    study.target.build_id = "release-one"
    study.run_backends = ["claude", "codex"]
    study.codex_model = "pinned-model"
    out = tmp_path / "out"
    out.mkdir()
    runner.write_lock(study, out)
    lock = out / "study.lock.json"
    original = lock.read_bytes()
    interrupted = out / "runs" / runner.plan_runs(study)[0].id / "steps.jsonl"
    interrupted.parent.mkdir(parents=True)
    interrupted.write_text("partially collected evidence\n")
    if change == "goal":
        study.tasks[0].goal = "a new task"
    elif change == "persona":
        study.personas[0].patience_steps += 1
    elif change == "model":
        study.codex_models = {"interview": "different-model"}
    else:
        study.target.build_id = "release-two"
    with pytest.raises(ValueError, match="fresh out_dir"):
        await runner.run_study(study, out, only=["__r1"])
    assert interrupted.read_text() == "partially collected evidence\n"
    assert lock.read_bytes() == original


def test_resume_checks_local_asset_and_preserves_outputs(tmp_path):
    study = _study(tmp_path)
    folder = tmp_path / "site"
    folder.mkdir()
    page = folder / "index.html"
    page.write_text("before")
    study.target = study.target.model_copy(update={"kind": "static", "folder": str(folder), "url": None})
    out = tmp_path / "out"
    out.mkdir()
    runner.write_lock(study, out)
    original = (out / "study.lock.json").read_bytes()
    page.write_text("after")
    with pytest.raises(ValueError, match="target build changed"):
        runner.write_lock(study, out)
    assert (out / "study.lock.json").read_bytes() == original


def test_legacy_lock_allows_terminal_subset_but_cannot_prove_build_for_new_observations(tmp_path):
    study = _study(tmp_path, personas=1, tasks=1)
    folder = tmp_path / "site"
    folder.mkdir()
    (folder / "index.html").write_text("one build")
    study.target = study.target.model_copy(update={"kind": "static", "folder": str(folder), "url": None})
    out = tmp_path / "out"
    spec, new = runner.plan_runs(study)[:2]
    done = out / "runs" / spec.id
    done.mkdir(parents=True)
    (done / "outcome.json").write_text(json.dumps({"status": "done", "model": study.model}))
    legacy = json.dumps({"study": study.model_dump(mode="json"), "models": {"persona": study.model}})
    (out / "study.lock.json").write_text(legacy)
    assert runner.write_lock(study, out, [spec]) == []
    with pytest.raises(ValueError, match="historical lock did not record the target build"):
        runner.write_lock(study, out, [new])
    assert (out / "study.lock.json").read_text() == legacy


def test_resume_checks_actual_outcomes_and_refuses_orphans(tmp_path):
    study = _study(tmp_path)
    out = tmp_path / "out"
    spec = runner.plan_runs(study)[0]
    run = out / "runs" / spec.id
    run.mkdir(parents=True)
    outcome = run / "outcome.json"
    outcome.write_text(json.dumps({"status": "done", "backend": "codex", "model": "wrong"}))
    with pytest.raises(ValueError, match="without a study lock"):
        runner.write_lock(study, out)
    assert not (out / "study.lock.json").exists()
    (out / "study.lock.json").write_text(json.dumps({"study": study.model_dump(mode="json")}))
    with pytest.raises(ValueError, match=f"recorded session {spec.id}"):
        runner.write_lock(study, out)
    assert json.loads(outcome.read_text())["model"] == "wrong"


def test_legacy_hosted_study_can_resume_and_detect_changed_codex_default(tmp_path, monkeypatch):
    study = _study(tmp_path)
    study.backend = "codex"
    out = tmp_path / "out"
    out.mkdir()
    legacy_pins = {role: "codex:gpt-a" for role in runner._ROLES if role != "matcher"}
    study.codex_models = {"matcher": "gpt-matcher"}
    (out / "study.lock.json").write_text(json.dumps({"study": study.model_dump(mode="json"), "models": legacy_pins}))
    monkeypatch.setattr("ux_swarm.config.default_codex_model", lambda: "gpt-a")
    assert runner.write_lock(study, out) == runner.plan_runs(study)
    monkeypatch.setattr("ux_swarm.config.default_codex_model", lambda: "gpt-b")
    with pytest.raises(ValueError, match="persona backend or model changed"):
        runner.write_lock(study, out)


async def test_overlapping_runners_cannot_retry_the_same_session(tmp_path, monkeypatch):
    study = _study(tmp_path, personas=1, tasks=1)
    out = tmp_path / "out"
    started, finish = asyncio.Event(), asyncio.Event()

    async def session(study, spec, directory, url):
        started.set()
        await finish.wait()
        (directory / "outcome.json").write_text('{"status":"done"}')
        return claude.ClaudeResult(True, "", None)

    monkeypatch.setattr(runner, "run_session", session)
    first = asyncio.create_task(runner.run_study(study, out, only=["__r1"]))
    await asyncio.wait_for(started.wait(), timeout=10)
    try:
        with pytest.raises(ValueError, match="Another runner"):
            await runner.run_study(study, out, only=["__r1"])
    finally:
        finish.set()
        await first


def test_device_failed_detected_from_init(tmp_path):
    log = tmp_path / "agent.jsonl"
    log.write_text(json.dumps({"type": "system", "mcp_servers": [{"name": "device", "status": "failed"}]}) + "\n")
    assert runner.device_failed(log)
    log.write_text(json.dumps({"type": "system", "mcp_servers": [{"name": "device", "status": "connected"}]}) + "\n")
    assert not runner.device_failed(log)
