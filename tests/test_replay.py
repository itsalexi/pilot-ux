import json
import re

import pytest
from PIL import Image

from pilot_ux.config import Study, Target, Task, load_persona_ref
from pilot_ux.replay import build_replay, collect_replay, render_replay
from pilot_ux.runner import plan_runs


@pytest.fixture
def study():
    return Study(name="Playback", target=Target(kind="proto", viewport=(40, 80)),
                 personas=[load_persona_ref("default/detail-checker")], runs=4,
                 tasks=[Task(id="save", goal="Save my work", success_criteria=["Saved"])])


def record(out, spec, rows, status=None):
    folder = out / "runs" / spec.id
    (folder / "shots").mkdir(parents=True)
    (folder / "steps.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    if status:
        (folder / "outcome.json").write_text(json.dumps({"status": status}))
    return folder


def frame(number, tool="look", **extra):
    return {"i": number, "tool": tool, "args": {}, "thought": "Thinking aloud.",
            "shot": f"shots/{number:04d}.png", **extra}


def export(out, study, ids=None, start_step=None):
    output = out / "replay.html"
    assert build_replay(study, out, output, session_ids=ids, start_step=start_step) == output
    html = output.read_text()
    data = re.search(r"""<script\b[^>]*\bid=["']replay-data["'][^>]*>(.*?)</script>""", html, re.S)
    assert data is not None
    return json.loads(data[1]), html


def test_replay_uses_before_frame_for_taps_and_only_emits_recorded_public_fields(tmp_path, study):
    spec = plan_runs(study)[0]
    line = "I can see </script><section>this</section>."
    folder = record(tmp_path, spec, [
        frame(0, ts=1000, thought=line),
        frame(1, "tap", ts=1004, args={"x": 10, "y": 60}, say="I'll tap here."),
        frame(2, "type_text", ts=1010, args={"text": "PRIVATE_TYPED_VALUE"}),
    ], "gave_up")
    (folder / "agent.jsonl").write_text('{"analysis":"PRIVATE_ANALYSIS"}\n')
    Image.new("RGB", (40, 80), "red").save(folder / "shots/0000.png")
    Image.new("RGB", (80, 40), "blue").save(folder / "shots/0001.png")
    (folder / "shots/0002.png").write_bytes((folder / "shots/0001.png").read_bytes())

    payload, html = export(tmp_path, study, [spec.id])
    assert "PRIVATE_TYPED_VALUE" not in html and "PRIVATE_ANALYSIS" not in html
    assert line not in html
    assert len(payload["images"]) == 2
    assert all(url.startswith("data:image/") for url in payload["images"])
    session, = payload["sessions"]
    assert session["outcome"] == "Gave up"
    first, tapped, typed = session["steps"]
    assert first["before"] is None and first["say"] == line
    assert tapped["before"] == first["image"] and tapped["image"] != first["image"]
    assert tapped["say"] == "I'll tap here."
    assert (tapped["x"], tapped["y"]) == (0.25, 0.75)
    assert typed["before"] == typed["image"] == tapped["image"]
    assert typed["x"] is None and typed["y"] is None
    assert [s["time"] for s in session["steps"]] == [0, 4, 10]


def test_missing_or_nonadjacent_shot_never_supplies_a_tap_marker(tmp_path, study):
    spec = plan_runs(study)[0]
    folder = record(tmp_path, spec, [
        frame(0), frame(1), frame(2, "tap", args={"x": 10, "y": 20}),
        frame(4, "tap", args={"x": 10, "y": 20}),
    ])
    for step in (0, 2, 4):
        Image.new("RGB", (40, 80)).save(folder / f"shots/{step:04d}.png")
    payload, _ = export(tmp_path, study)
    first, missing, after_missing, after_gap = payload["sessions"][0]["steps"]
    assert first["time"] is None and missing["image"] is None
    for step in [after_missing, after_gap]:
        assert step["before"] is None
        assert step["x"] is None and step["y"] is None


def test_player_embeds_only_the_recorded_images(tmp_path, study):
    spec = plan_runs(study)[0]
    folder = record(tmp_path, spec, [frame(0)])
    Image.new("RGB", (40, 80), "red").save(folder / "shots/0000.png")
    payload, html = export(tmp_path, study)
    embedded = re.findall(r"data:image/[a-z]+;base64,[A-Za-z0-9+/=]+", html)
    assert len(payload["images"]) == 1
    assert embedded == payload["images"]


def test_explicit_order_and_verified_vs_unverified_outcomes(tmp_path, study):
    specs = plan_runs(study)
    for spec, outcome in zip(specs, ["done", "done", "gave_up", None]):
        folder = record(tmp_path, spec, [frame(0)], outcome)
        Image.new("RGB", (40, 80)).save(folder / "shots/0000.png")
    (tmp_path / "runs" / specs[0].id / "verdict.json").write_text('{"verdict":"verified"}')
    ids = [spec.id for spec in reversed(specs)]
    payload, _ = export(tmp_path, study, ids)
    assert [session["id"] for session in payload["sessions"]] == ids
    assert [session["outcome"] for session in payload["sessions"]] == [
        "Incomplete", "Gave up", "Claimed success", "Verified success"
    ]


def test_explicit_unrecorded_session_is_an_error(tmp_path, study):
    with pytest.raises(ValueError):
        export(tmp_path, study, [plan_runs(study)[0].id])


def test_optional_embedded_replay_handles_empty_studies(tmp_path, study):
    assert collect_replay(study, tmp_path) == {"title": study.name, "sessions": [], "images": []}
    with pytest.raises(ValueError, match="no recorded device steps"):
        build_replay(study, tmp_path, tmp_path / "empty.html")
    assert not (tmp_path / "empty.html").exists()


def test_standalone_and_embedded_player_render_identically(tmp_path, study):
    spec = plan_runs(study)[0]
    record(tmp_path, spec, [frame(0)])
    _, html = export(tmp_path, study, [spec.id])
    assert html == render_replay(collect_replay(study, tmp_path, [spec.id]))


def test_start_step_is_a_recorded_id_in_the_first_selected_session(tmp_path, study):
    a, b = plan_runs(study)[:2]
    record(tmp_path, a, [frame(0), frame(1)])
    record(tmp_path, b, [frame(0), frame(7)])
    ids = [b.id, a.id]
    default, _ = export(tmp_path, study, ids)
    assert "start" not in default
    payload, html = export(tmp_path, study, ids, start_step=7)
    assert payload["start"] == {"session": b.id, "step": 7}
    with pytest.raises(ValueError, match="no recorded step 1 in first session"):
        export(tmp_path, study, ids, start_step=1)
    assert (tmp_path / "replay.html").read_text() == html


@pytest.mark.parametrize("artifact", ["shot", "steps"])
def test_symlinks_cannot_export_outside_data(tmp_path, study, artifact):
    spec = plan_runs(study)[0]
    folder = record(tmp_path, spec, [frame(0), frame(1)])
    Image.new("RGB", (40, 80)).save(folder / "shots/0000.png")
    if artifact == "shot":
        outside = tmp_path / "private.png"
        Image.new("RGB", (40, 80), "orange").save(outside)
        (folder / "shots/0001.png").symlink_to(outside)
    else:
        outside = tmp_path / "private.jsonl"
        outside.write_text(json.dumps(frame(0, thought="PRIVATE_OUTSIDE_LINE")) + "\n")
        (folder / "steps.jsonl").unlink()
        (folder / "steps.jsonl").symlink_to(outside)

    try:
        payload, html = export(tmp_path, study, [spec.id])
    except ValueError:
        return
    assert "PRIVATE_OUTSIDE_LINE" not in html
    assert len(payload["images"]) <= 1
