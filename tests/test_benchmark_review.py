import csv
import json

import pytest
from PIL import Image, PngImagePlugin

from ux_swarm.benchmark_review import export_review, score_review


@pytest.fixture
def benchmark(tmp_path):
    base = tmp_path / "benchmark"
    # The preregistered singleton deliberately appears after the other generic run.
    cases = [
        ("private-card-a", "persona", 1, False, ["No receipt", "Unclear fee"]),
        ("private-control-b", "generic", 2, False, ["No receipt", "Repeated submit"]),
        ("private-control-a", "generic", 1, True, ["No receipt", "No receipt"]),
        ("private-card-b", "persona", 2, False, ["Empty receipt link"]),
    ]
    sessions = []
    for run_id, arm, slot, singleton, descriptions in cases:
        sessions.append({"run_id": run_id, "task": "save", "panel": 1, "slot": slot,
                         "arm": arm, "singleton": singleton})
        folder = base / "study" / "runs" / run_id
        (folder / "shots").mkdir(parents=True)
        (folder / "outcome.json").write_text(json.dumps({
            "status": "gave_up", "steps": 2, "contaminated": False, "reason": "PRIVATE OUTCOME",
        }))
        steps = []
        for i, color in enumerate(["red", "blue"]):
            path = f"shots/{i:04d}.png"
            info = PngImagePlugin.PngInfo()
            info.add_text("comment", "PRIVATE IMAGE METADATA")
            Image.new("RGB", (16, 24), color).save(folder / path, pnginfo=info)
            tool, args = "look", {}
            if i == 1:
                if run_id == "private-card-b":
                    tool, args = "type_text", {"text": "PRIVATE TYPED VALUE"}
                else:
                    tool, args = "tap", {"x": 9, "y": 17, "irrelevant": "PRIVATE ARGUMENT"}
            steps.append({"i": i, "tool": tool, "args": args, "shot": path, "changed": True,
                          "thought": "PRIVATE TRANSCRIPT"})
        (folder / "steps.jsonl").write_text("\n".join(map(json.dumps, steps)) + "\n")
        findings = [{"description": description, "screen": "Checkout", "element": "Receipt",
                     "severity": 3, "steps": [1], "evidence_quote": "PRIVATE QUOTE",
                     "suggested_fix": "PRIVATE FIX", "is_prototype_gap": False,
                     "agent_misread": False, "category": "feedback"}
                    for description in descriptions]
        (folder / "findings.json").write_text(json.dumps({"findings": findings}))
    (base / "benchmark.json").write_text(json.dumps({"tasks": {"save": "Save my receipt"}, "sessions": sessions}))
    return base


def read_rows(path):
    with path.open(newline="") as source:
        return list(csv.DictReader(source))


def write_rows(path, rows):
    with path.open("w", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)


def adjudicate(rows):
    supported = {"No receipt": "receipt", "Unclear fee": "fee", "Repeated submit": "submit"}
    for row in rows:
        key = supported.get(row["description"], "")
        row.update(decision="supported" if key else "fixture_gap", canonical_id=key,
                   reviewer="Image reviewer", reviewer_kind="ai", reason="Checked both recorded frames.")


def test_public_packet_exposes_rendered_evidence_and_hides_private_provenance(benchmark, tmp_path):
    review_dir = tmp_path / "review"
    path = export_review(benchmark, review_dir)
    assert path == review_dir / "review.csv"
    rows = read_rows(path)
    assert len(rows) == len({row["candidate_id"] for row in rows}) == 7
    assert set(rows[0]) == {
        "candidate_id", "goal", "screen", "element", "description", "evidence", "actions",
        "decision", "canonical_id", "reviewer", "reviewer_kind", "reason",
    }
    assert all(row["evidence"] and not row["decision"] for row in rows)
    assert all(row["goal"] == "Save my receipt" for row in rows)
    for row in rows:
        action = row["actions"].lower()
        if row["description"] == "Empty receipt link":
            assert "typ" in action
        else:
            assert "tap" in action and "9" in action and "17" in action
    colors = set()
    for file in sorted(review_dir.rglob("*")):
        if file.is_file():
            contents = file.read_bytes() + file.relative_to(review_dir).as_posix().encode()
            for private in [b"private-card", b"private-control", b"PRIVATE", b"irrelevant",
                            b"shots/0001.png", b'"arm":', b'"singleton":']:
                assert private not in contents
            if file.suffix == ".png":
                with Image.open(file) as image:
                    colors.update(color for _, color in image.convert("RGB").getcolors(image.width * image.height))
    assert {(255, 0, 0), (0, 0, 255)} <= colors


def test_comparison_uses_blind_canonical_ids_and_preregistered_singleton(benchmark, tmp_path):
    review_dir = tmp_path / "review"
    path = export_review(benchmark, review_dir)
    rows = read_rows(path)
    adjudicate(rows)
    # A reviewer can sort their spreadsheet. The join must be independent of row position.
    write_rows(path, rows[::-1])
    panel, = score_review(benchmark, review_dir)["panels"]
    assert panel["complete"] is True
    assert set(panel["singleton"]) == {"receipt"}
    assert set(panel["generic"]) == {"receipt", "submit"}
    assert set(panel["persona"]) == {"receipt", "fee"}
    assert panel["generic_only"] == ["submit"] and panel["persona_only"] == ["fee"]
    assert panel["shared"] == ["receipt"]
    assert panel["mean_single_generic"] == 1.5


@pytest.mark.parametrize("problem", ["pending", "missing_frame", "contaminated"])
def test_incomplete_panel_withholds_exclusivity(benchmark, tmp_path, problem):
    folder = benchmark / "study/runs/private-control-a"
    if problem == "missing_frame":
        (folder / "shots/0001.png").unlink()
    if problem == "contaminated":
        path = folder / "outcome.json"
        path.write_text(json.dumps({**json.loads(path.read_text()), "contaminated": True}))
    review_dir = tmp_path / "review"
    path = export_review(benchmark, review_dir)
    rows = read_rows(path)
    adjudicate(rows)
    if problem in ("pending", "missing_frame"):
        for row in (rows[:1] if problem == "pending" else rows):
            row.update(decision="", reviewer="", reviewer_kind="", canonical_id="", reason="")
    write_rows(path, rows)
    panel, = score_review(benchmark, review_dir)["panels"]
    assert panel["complete"] is False
    assert all(panel[key] is None for key in ("persona_only", "generic_only", "shared"))


@pytest.mark.parametrize("problem", ["unknown_candidate", "missing_frame", "missing_reviewer_kind", "malformed_tap"])
def test_supported_finding_requires_a_real_candidate_evidence_and_provenance(benchmark, tmp_path, problem):
    recording = benchmark / "study/runs/private-control-a"
    if problem == "missing_frame":
        (recording / "shots/0001.png").unlink()
    if problem == "malformed_tap":
        transcript = recording / "steps.jsonl"
        frames = [json.loads(line) for line in transcript.read_text().splitlines()]
        frames[1]["args"] = {"x": "PRIVATE MALFORMED COORDINATE", "y": 17}
        transcript.write_text("\n".join(map(json.dumps, frames)) + "\n")
    review_dir = tmp_path / "review"
    path = export_review(benchmark, review_dir)
    rows = read_rows(path)
    adjudicate(rows)
    if problem == "unknown_candidate":
        rows.append({**rows[0], "candidate_id": "fabricated", "canonical_id": "invented-issue"})
    if problem == "missing_reviewer_kind":
        rows[0]["reviewer_kind"] = ""
    write_rows(path, rows)
    with pytest.raises(ValueError):
        score_review(benchmark, review_dir)


@pytest.mark.parametrize("edit", ["annotation", "distributed_png"])
def test_score_rejects_evidence_changed_after_masked_export(benchmark, tmp_path, edit):
    review_dir = tmp_path / "review"
    path = export_review(benchmark, review_dir)
    rows = read_rows(path)
    adjudicate(rows)
    write_rows(path, rows)
    if edit == "annotation":
        source = benchmark / "study/runs/private-card-a/findings.json"
        data = json.loads(source.read_text())
        data["findings"][0]["description"] = "A different explanation."
        source.write_text(json.dumps(data))
    else:
        supported = next(row for row in rows if row["decision"] == "supported")
        first_frame = supported["evidence"].split(" | ")[0]
        Image.new("RGB", (16, 24), "green").save(review_dir / first_frame)
    with pytest.raises(ValueError):
        score_review(benchmark, review_dir)


@pytest.mark.parametrize("target", ["url", "ios"])
def test_complete_panel_reports_unverified_server_state_for_remote_targets(benchmark, tmp_path, target):
    source = benchmark / "benchmark.json"
    manifest = json.loads(source.read_text())
    manifest["study"] = {"target": {"kind": target}}
    source.write_text(json.dumps(manifest))
    review_dir = tmp_path / "review"
    path = export_review(benchmark, review_dir)
    rows = read_rows(path)
    adjudicate(rows)
    write_rows(path, rows)

    result = score_review(benchmark, review_dir)
    panel, = result["panels"]
    assert panel["complete"] is True and panel["persona_only"] == ["fee"]
    assert result["initial_state"]["server_state"] == "unverified"
    assert result["initial_state"]["target_kind"] == target
    assert panel["attribution"] == "descriptive_only"
