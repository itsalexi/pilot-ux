import json

import pytest
from PIL import Image

from pilot_ux import analyze
from pilot_ux.config import load_study


def _setup(tmp_path):
    p = tmp_path / "study.yaml"
    p.write_text("name: s\ntarget: {kind: url, url: 'http://x'}\n"
                 "tasks: [{id: t, goal: g, success_criteria: [c]}]\npersonas: [{ref: default/older-non-techy}]\nruns: 1\n")
    study = load_study(p)
    rd = tmp_path / "out/runs/older-non-techy__t__r1"
    (rd / "shots").mkdir(parents=True)
    (rd / "shots/0000.png").write_bytes(b"x")
    (rd / "steps.jsonl").write_text(json.dumps({"i": 0, "tool": "done", "args": {"summary": "I paid"},
                                                "thought": "done!", "shot": "shots/0000.png", "changed": True}) + "\n")
    (rd / "outcome.json").write_text(json.dumps({"status": "done", "summary": "I paid", "steps": 1}))
    return study, tmp_path / "out", rd


async def test_done_but_not_verified_is_failure(tmp_path, monkeypatch):
    study, out, rd = _setup(tmp_path)
    seen = {}

    async def fake_ask(model, system, prompt, schema, files=None, **k):
        seen["prompt"] = prompt
        return {"verdict": "not_verified", "reason": "screen shows unpaid"}

    monkeypatch.setattr(analyze.agents.claude, "ask_json", fake_ask)
    await analyze.verify(study, out)
    assert "I paid" not in seen["prompt"]  # the claim is withheld from the verifier
    v = json.loads((rd / "verdict.json").read_text())
    assert analyze.effective_status(json.loads((rd / "outcome.json").read_text()), v) == "failed_claim"
    assert analyze.effective_status({"status": "done"}, {"verdict": "verified"}) == "success"
    assert analyze.effective_status({"status": "gave_up"}, None) == "gave_up"


def _record(rd, tools):
    steps = []
    for i, tool in enumerate(tools):
        path = f"shots/{i:04d}.png"
        Image.new("RGB", (8, 8), (10 * i, 30, 50)).save(rd / path)
        steps.append({"i": i, "tool": tool, "args": {}, "shot": path, "thought": "private utterance",
                      "changed": True})
    (rd / "steps.jsonl").write_text("".join(json.dumps(row) + "\n" for row in steps))
    (rd / "outcome.json").write_text(json.dumps({"status": "done", "steps": len(steps), "summary": "I paid"}))


async def test_persistence_uses_only_last_reopen_before_later_edits(tmp_path, monkeypatch):
    study, out, rd = _setup(tmp_path)
    task = study.tasks[0]
    assert "verify_after" not in study.model_dump()["tasks"][0]  # older frozen benchmarks
    task.verify_after = "reopen"
    assert study.model_dump()["tasks"][0]["verify_after"] == "reopen"
    _record(rd, ["look", "reopen", "type_text", "reopen", "type_text", "done"])
    # A previous ordinary verdict has no evidence for this check.
    (rd / "verdict.json").write_text('{"verdict":"verified","reason":"final screen"}')

    async def judge(study, role, system, prompt, schema, files):
        assert files == {"reopened.png": rd / "shots/0003.png"}
        assert "reopened" in prompt and "I paid" not in prompt and "private utterance" not in prompt
        return {"verdict": "not_verified", "reason": "The reopened list is empty."}

    monkeypatch.setattr(analyze.agents, "ask_json", judge)
    await analyze.verify(study, out)
    verdict = json.loads((rd / "verdict.json").read_text())
    assert verdict["verdict"] == "not_verified"
    assert verdict["evidence_step"] == 3
    assert verdict["verify_after"] == "reopen"


@pytest.mark.parametrize("cause, expected", [("never_reopened", "not_verified"), ("missing_trace", "unclear"),
                                             ("missing_frame", "unclear"), ("corrupt_frame", "unclear"),
                                             ("later_frame", "unclear")])
async def test_persistence_requires_recorded_reopen_and_its_frame(tmp_path, monkeypatch, cause, expected):
    study, out, rd = _setup(tmp_path)
    study.tasks[0].verify_after = "reopen"
    _record(rd, ["look", "done"] if cause == "never_reopened" else ["look", "reopen", "done"])
    trace = rd / "steps.jsonl"
    if cause == "missing_trace":
        trace.unlink()
    elif cause == "missing_frame":
        (rd / "shots/0001.png").unlink()
    elif cause == "corrupt_frame":
        (rd / "shots/0001.png").write_bytes(b"bad image")
    elif cause == "later_frame":
        trace.write_text(trace.read_text().replace("shots/0001.png", "shots/0002.png"))

    async def unexpected(*args, **kwargs):
        pytest.fail("incomplete reopen evidence reached the model")

    monkeypatch.setattr(analyze.agents, "ask_json", unexpected)
    await analyze.verify(study, out)
    assert json.loads((rd / "verdict.json").read_text())["verdict"] == expected


def test_reopen_verification_needs_a_supported_target(tmp_path):
    study, _, _ = _setup(tmp_path)
    config = study.model_dump()
    config["target"]["kind"] = "ios"
    config["tasks"][0]["verify_after"] = "reopen"
    with pytest.raises(ValueError, match="requires a web target"):
        type(study).model_validate(config)


async def test_merge_keeps_unassigned_findings(tmp_path, monkeypatch):
    study, out, rd = _setup(tmp_path)
    (rd / "findings.json").write_text(json.dumps({"findings": [
        {"screen": "s", "element": "e", "description": "d1", "severity": 3, "steps": [0], "evidence_quote": "q",
         "suggested_fix": "f", "is_prototype_gap": False, "agent_misread": False, "category": "c"},
        {"screen": "s", "element": "e2", "description": "d2", "severity": 1, "steps": [0], "evidence_quote": "q2",
         "suggested_fix": "f2", "is_prototype_gap": False, "agent_misread": False, "category": "c"}]}))

    async def fake_ask(model, system, prompt, schema, files=None, **k):
        return {"issues": [{"title": "T", "description": "D", "suggested_fix": "F", "members": ["F1"]}]}

    monkeypatch.setattr(analyze.agents.claude, "ask_json", fake_ask)
    issues = await analyze.merge(study, out)
    assert len(issues) == 2
    assert issues[0]["severity"] == 3 and issues[0]["frequency"] == 1.0


def test_annotator_shots_are_capped_but_keep_the_start_and_the_ending(tmp_path):
    from pilot_ux.analyze import annotator_shots
    shots = tmp_path / "shots"
    shots.mkdir()
    for i in range(60):
        (shots / f"{i:04d}.png").write_bytes(b"x")
    got = annotator_shots(tmp_path, cap=20)
    assert len(got) == 20
    names = sorted(got)
    assert names[0] == "shots/0000.png" and names[-1] == "shots/0059.png"
    assert all(f"shots/{i:04d}.png" in got for i in range(52, 60))  # the ending is where judgments live
    assert all(got[n] == tmp_path / n for n in names)


def test_annotator_shots_send_everything_when_under_the_cap(tmp_path):
    from pilot_ux.analyze import annotator_shots
    (tmp_path / "shots").mkdir()
    for i in range(5):
        (tmp_path / "shots" / f"{i:04d}.png").write_bytes(b"x")
    assert sorted(annotator_shots(tmp_path, cap=20)) == [f"shots/{i:04d}.png" for i in range(5)]
