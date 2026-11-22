import json

import pytest
import yaml
from PIL import Image

from ux_swarm.cli import main
from ux_swarm.config import Study, Target, Task, load_persona_ref
from ux_swarm.recheck import Witness, compare
from ux_swarm.runner import plan_runs


def store(path, data):
    path.write_text(json.dumps(data))


@pytest.fixture
def outputs(tmp_path):
    study = Study(
        name="Demo", target=Target(kind="static"), runs=1,
        personas=[load_persona_ref("default/detail-checker")],
        tasks=[Task(id="save", goal="Save my work", success_criteria=["Title is in the list"])],
    )
    spec, = plan_runs(study)
    issue = {
        "id": "I1", "title": "Saved title missing from list", "runs": [spec.id], "personas": [spec.persona.id],
        "tasks": ["save"], "evidence": [{"run": spec.id, "steps": [0], "quote": "Where is it?", "finding": "F1"}],
        "severity": 3, "frequency": 1, "prototype_gap": False, "description": "Title is gone",
        "suggested_fix": "Persist the saved title.",
    }
    for folder, timestamp, status in (("before", 100, "gave_up"), ("after", 200, "done")):
        out = tmp_path / folder
        rd = out / "runs" / spec.id
        (rd / "shots").mkdir(parents=True)
        Image.new("RGB", (20, 30), "white").save(rd / "shots/0000.png")
        store(rd / "outcome.json", {"status": status, "backend": "claude", "model": study.model, "steps": 1})
        store(rd / "steps.jsonl", {
            "i": 0, "ts": timestamp, "thought": "Where is it?", "shot": "shots/0000.png",
            "tool": "look", "args": {}, "changed": True,
        })
        if status == "done":
            store(rd / "verdict.json", {"verdict": "verified", "reason": "The title is in the list."})
        roles = ("verifier", "annotator", "merger", "persona", "interview")
        store(out / "study.lock.json", {"study": study.model_dump(), "models": dict.fromkeys(roles, "claude:" + study.model)})
        store(out / "issues.json", [issue] if folder == "before" else [])
    witness = {
        "before_version": "v1", "after_version": "v2", "reviewer": "AI reviewer",
        "observations": [{
            "issue": "I1", "before_run": spec.id, "before_step": 0, "after_run": spec.id, "after_step": 0,
            "result": "improved", "note": "My plants lists the new title after returning.",
        }],
    }
    return tmp_path / "before", tmp_path / "after", witness


def test_missing_issue_with_verified_success_is_inconclusive(outputs):
    before, after, _ = outputs
    result = compare(before, after)
    assert result["task_outcomes"]["save"] == {"before": {"gave_up": 1}, "after": {"verified": 1}}
    assert result["issues"][0]["status"] == "inconclusive"


def test_issue_ids_are_local_and_title_matches_only_suggest_candidates(outputs):
    before, after, _ = outputs
    item, = json.loads((before / "issues.json").read_text())
    store(after / "issues.json", [{**item, "id": "I7"}, {**item, "title": "Unrelated notification permission"}])
    issue, = compare(before, after)["issues"]
    assert issue["candidates"] == [{"id": "I7", "title": item["title"]}]
    assert issue["status"] == "inconclusive"


def test_witness_cli_writes_report_and_observations(outputs, tmp_path, capsys):
    before, after, witness = outputs
    witness_path = tmp_path / "witness.yml"
    witness_path.write_text(yaml.safe_dump(witness))
    main(["recheck", str(before), str(after), "--witness", str(witness_path)])
    assert "improvement witnessed" in capsys.readouterr().out
    issue, = json.loads((after / "recheck.json").read_text())["issues"]
    assert issue["observations"][0]["reviewer"] == "AI reviewer"
    html = (after / "report.html").read_text()
    assert "Before and after" in html and "My plants lists the new title" in html
    assert (after / "report.md").is_file()
    with pytest.raises(SystemExit, match="already contains observations"):
        main(["recheck", str(before), str(after)])


@pytest.mark.parametrize("fault", ["same-dir", "copied-recording", "persona-model", "goal", "criteria", "analysis-model"])
def test_incompatible_or_reused_data(outputs, fault):
    before, after, _ = outputs
    rd, = (after / "runs").iterdir()
    if fault == "same-dir":
        after = before
    elif fault == "copied-recording":
        (rd / "steps.jsonl").write_bytes((before / "runs" / rd.name / "steps.jsonl").read_bytes())
    elif fault == "persona-model":
        data = json.loads((rd / "outcome.json").read_text())
        store(rd / "outcome.json", {**data, "model": "different"})
    else:
        lock = json.loads((after / "study.lock.json").read_text())
        if fault == "analysis-model":
            lock["models"]["verifier"] = "new"
        elif fault == "criteria":
            lock["study"]["tasks"][0]["success_criteria"] = ["Different"]
        else:
            lock["study"]["tasks"][0]["goal"] = "Different"
        store(after / "study.lock.json", lock)
    with pytest.raises(ValueError):
        compare(before, after)


@pytest.mark.parametrize("fault", ["before-step", "after-step", "outside-run", "same-version"])
def test_witness_needs_cited_issue_frame_and_genuine_after_frame(outputs, fault):
    before, after, witness = outputs
    observation = witness["observations"][0]
    if fault == "same-version":
        witness["after_version"] = witness["before_version"]
    elif fault == "outside-run":
        record = after / "runs" / observation["after_run"] / "steps.jsonl"
        store(record, {**json.loads(record.read_text()), "shot": str(before / "study.lock.json")})
    else:
        observation[fault.replace("-", "_")] = 300
    with pytest.raises(ValueError):
        compare(before, after, Witness.model_validate(witness))
