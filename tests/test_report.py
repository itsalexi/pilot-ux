import json

from ux_swarm import report
from ux_swarm.config import load_study


def _out(tmp_path):
    p = tmp_path / "study.yaml"
    p.write_text("name: s\ntarget: {kind: url, url: 'http://x'}\n"
                 "tasks: [{id: t, goal: g, success_criteria: [c]}]\n"
                 "personas: [{ref: default/older-non-techy}, {ref: default/detail-checker}]\nruns: 1\n")
    study = load_study(p)
    out = tmp_path / "out"
    for pid, status in (("older-non-techy", "gave_up"), ("detail-checker", "done")):
        rd = out / f"runs/{pid}__t__r1"
        (rd / "shots").mkdir(parents=True)
        from PIL import Image
        Image.new("RGB", (390, 844), "white").save(rd / "shots/0000.png")
        (rd / "outcome.json").write_text(json.dumps({"status": status, "steps": 1, "contaminated": False}))
        (rd / "steps.jsonl").write_text(json.dumps({"i": 0, "tool": "look", "args": {}, "thought": "hm",
                                                    "shot": "shots/0000.png", "changed": True}) + "\n")
    (out / "runs/detail-checker__t__r1/verdict.json").write_text(json.dumps({"verdict": "verified", "reason": "ok"}))
    ev = lambda r: [{"run": r, "steps": [0], "quote": "where is it", "finding": "F1"}]
    issues = [
        {"id": "I1", "title": "Rare catastrophe", "severity": 4.0, "frequency": 0.5, "personas": ["older-non-techy"],
         "prototype_gap": False, "evidence": ev("older-non-techy__t__r1"), "description": "d", "suggested_fix": "f",
         "runs": ["older-non-techy__t__r1"], "tasks": ["t"], "category": "other", "agent_misread_share": 0},
        {"id": "I2", "title": "Common major", "severity": 3.0, "frequency": 1.0, "personas": ["a", "b"],
         "prototype_gap": False, "evidence": ev("detail-checker__t__r1"), "description": "d", "suggested_fix": "f",
         "runs": ["detail-checker__t__r1"], "tasks": ["t"], "category": "other", "agent_misread_share": 0},
        {"id": "I3", "title": "Unbuilt button", "severity": 2.0, "frequency": 1.0, "personas": ["a", "b"],
         "prototype_gap": True, "evidence": ev("detail-checker__t__r1"), "description": "d", "suggested_fix": "f",
         "runs": ["detail-checker__t__r1"], "tasks": ["t"], "category": "other", "agent_misread_share": 0}]
    (out / "issues.json").write_text(json.dumps(issues))
    return study, out


def test_report_sorts_by_severity_times_frequency(tmp_path):
    study, out = _out(tmp_path)
    md, html = report.build(study, out)
    text = md.read_text()
    assert text.index("Common major") < text.index("Rare catastrophe")
    assert text.index("Rare catastrophe") < text.index("Unbuilt button")  # gaps listed separately, last
    assert "1/2" in text  # task success counts with verifier
    assert html.read_text().count("data:image/") >= 2


def test_report_has_no_praise_section(tmp_path):
    study, out = _out(tmp_path)
    md, _ = report.build(study, out)
    low = md.read_text().lower()
    for w in ("what worked", "strengths", "positives", "praise"):
        assert w not in low


def test_report_uses_locked_codex_models_in_both_formats(tmp_path):
    study, out = _out(tmp_path)
    locked_study = study.model_copy(update={"backend": "codex"})
    (out / "study.lock.json").write_text(json.dumps({
        "study": locked_study.model_dump(), "models": {"persona": "codex:gpt-pinned", "interview": "codex:gpt-pinned"},
        "claude_version": "2.1 (Claude Code)",
    }))
    for path in report.build(study, out):
        text = path.read_text()
        assert "persona models" in text and "codex:gpt-pinned" in text
        assert study.model not in text and "Claude Code" not in text


def test_report_uses_recorded_persona_and_per_run_interview_models(tmp_path):
    study, out = _out(tmp_path)
    study.runs = 2
    study.run_backends = ["claude", "codex"]
    study.codex_model = "gpt-configured"
    study.codex_models = {"interview": "gpt-interview"}
    added = out / "runs/detail-checker__t__r2"
    added.mkdir()
    (added / "outcome.json").write_text(json.dumps({"status": "gave_up", "backend": "codex", "model": "gpt-recorded"}))
    for path in report.build(study, out):
        text = path.read_text()
        assert f"claude:{study.model}, codex:gpt-recorded" in text
        assert f"claude:{study.model}, codex:gpt-interview" in text
        assert "gpt-configured" not in text
