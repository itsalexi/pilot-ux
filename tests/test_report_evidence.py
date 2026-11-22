import csv
import json
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

import pytest
from PIL import Image

from pilot_ux.config import Study, Target, Task, load_persona_ref
from pilot_ux.report import build
from pilot_ux.runner import plan_runs


QUIT_REASON = "I could not find the order confirmation."
CLOSE_TRIGGER = "I would leave if checkout showed <receipt> & charged twice."


class ReportPage(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links = []
        self.resources = []
        self.text = []
        self.in_code = False
        self.section = None
        self.sections = {}
        self.active_link = None
        self.link_labels = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a":
            self.links.append(attrs.get("href", ""))
            self.active_link = (self.links[-1], [])
        if tag == "section":
            self.section = attrs.get("id")
            self.sections[self.section] = []
        if "src" in attrs:
            self.resources.append(attrs["src"])
        if tag == "link" and attrs.get("rel") == "stylesheet":
            self.resources.append(attrs["href"])
        if tag in ("script", "style"):
            self.in_code = True

    def handle_endtag(self, tag):
        if tag == "a" and self.active_link:
            href, label = self.active_link
            self.link_labels.append((href, "".join(label).strip()))
            self.active_link = None
        if tag == "section":
            self.section = None
        if tag in ("script", "style"):
            self.in_code = False

    def handle_data(self, data):
        if not self.in_code:
            self.text.append(data)
            if self.section:
                self.sections[self.section].append(data)
            if self.active_link:
                self.active_link[1].append(data)


@pytest.fixture
def study():
    return Study(name="Checkout trial", target=Target(kind="url", url="http://localhost"),
                 tasks=[Task(id="checkout", goal="Finish my order", success_criteria=["Receipt displayed"])],
                 personas=[load_persona_ref("default/detail-checker")], runs=1)


@pytest.fixture
def recorded(tmp_path, study):
    run, = plan_runs(study)
    folder = tmp_path / "runs" / run.id
    (folder / "shots").mkdir(parents=True)
    (folder / "outcome.json").write_text(json.dumps({"status": "gave_up", "steps": 3, "reason": QUIT_REASON}))
    (folder / "interview.json").write_text(json.dumps({"answers": {"close_trigger": CLOSE_TRIGGER}}))
    steps = []
    for i in (0, 4, 7):
        shot = f"shots/{i:04d}.png"
        Image.new("RGB", (40, 80), (i, 0, 0)).save(folder / shot)
        steps.append(json.dumps({"i": i, "tool": "look", "shot": shot, "args": {},
                                 "thought": f"Looking at frame {i}.", "changed": True}))
    (folder / "steps.jsonl").write_text("\n".join(steps) + "\n")
    evidence = [{"run": run.id, "steps": [4, 404], "quote": "Looking at frame 4.", "finding": "F1"}]
    issue = {"id": "I1", "title": "Confirmation is ambiguous", "description": "No final confirmation.",
             "category": "feedback", "severity": 3, "frequency": 1, "agent_misread_share": 0,
             "personas": [run.persona.id], "runs": [run.id], "tasks": [run.task.id],
             "evidence": evidence, "suggested_fix": "Show the receipt.", "prototype_gap": False}
    gap = {**issue, "id": "I2", "title": "Unwired receipt link", "prototype_gap": True}
    (tmp_path / "issues.json").write_text(json.dumps([issue, gap]))
    (tmp_path / "eval").mkdir()
    (tmp_path / "eval/metrics.json").write_text(json.dumps({
        "recall": 0.75, "matched_in_scope": 3, "in_scope": 4, "false_positive_rate": 0.25,
        "stale_rate": 0, "non_gap_issues": 4, "labels": {"real": 3, "hallucinated": 1},
    }))
    return run


def test_report_links_findings_to_recorded_steps_and_preserves_curated_replay(tmp_path, study, recorded):
    run = recorded
    curated = tmp_path / "replay.html"
    curated.write_text("Curated playback selection")

    _, html_path = build(study, tmp_path)

    html = html_path.read_text()
    page = ReportPage(html)
    assert curated.read_text() == "Curated playback selection"
    assert not (tmp_path / "sessions.html").exists()
    assert "data:image/" in html
    assert all(resource.startswith(("data:", "about:blank", "#")) for resource in page.resources)
    linked_steps = set()
    for link in page.links:
        target = urlsplit(link)
        params = parse_qs(target.fragment)
        if params.get("session") == [run.id]:
            assert target.path == ""
            linked_steps.update(params.get("step", []))
    assert "4" in linked_steps
    assert linked_steps <= {"0", "4", "7"}
    assert f"#session={run.id}&amp;step=4" in html
    assert (f"#session={run.id}&step=4", "Step 2") in page.link_labels
    visible = " ".join(page.text)
    for text in [QUIT_REASON, CLOSE_TRIGGER, "Confirmation is ambiguous", "Unwired receipt link", "75%", "25%"]:
        assert text in visible


def test_reviewed_gap_and_note_appear_in_prioritized_findings(tmp_path, study, recorded):
    title = "Unwired receipt link"
    note = "The control is present, but it has no visible label."
    with (tmp_path / "eval/labels.csv").open("w", newline="") as labels:
        writer = csv.DictWriter(labels, fieldnames=["issue_id", "title", "human_label", "note"])
        writer.writeheader()
        writer.writerow({"issue_id": "I2", "title": title, "human_label": "real", "note": note})

    md, html = build(study, tmp_path)
    page = ReportPage(html.read_text())
    findings = " ".join(page.sections["findings"])
    assert title in findings and note in findings
    assert title not in " ".join(page.sections.get("gaps", []))
    assert f"### I2. {title}" in md.read_text()


def test_recheck_preserves_both_evidence_references_when_baseline_is_offline(tmp_path, study, recorded):
    run = recorded.id
    status = "improvement witnessed"
    note = "The revised receipt now shows the order number."
    baseline_run = "detail-checker__checkout__r2"
    recheck = {
        "before_dir": str(tmp_path / "unavailable-baseline"),
        "before_version": "baseline", "after_version": "current", "comparable_sessions": 1,
        "task_outcomes": {"checkout": {"before": {"gave_up": 1}, "after": {"gave_up": 1}}},
        "issues": [{"id": "I1", "title": "Missing order number", "status": status, "observations": [
            {"before_run": baseline_run, "before_step": 9, "after_run": run, "after_step": 7,
             "result": "improved", "reviewer": "Manual review", "note": note},
        ]}],
    }
    (tmp_path / "recheck.json").write_text(json.dumps(recheck))

    md, html = build(study, tmp_path)
    page = ReportPage(html.read_text())
    comparison = " ".join(page.sections["recheck"])
    for text in [status, note, "Manual review", baseline_run, run]:
        assert text in comparison and text in md.read_text()
    assert "step ID 9" in comparison
    assert (f"#session={run}&step=7", "Step 3") in page.link_labels
    assert all(baseline_run not in link for link in page.links)
    assert f"{baseline_run} step ID 9" in md.read_text() and f"{run} step ID 7" in md.read_text()


def test_report_without_recorded_sessions_has_no_playback_links(tmp_path, study):
    md, html = build(study, tmp_path)
    assert study.name in md.read_text()
    page = ReportPage(html.read_text())
    assert study.name in " ".join(page.text)
    assert not (tmp_path / "sessions.html").exists()
    assert all("session" not in parse_qs(urlsplit(link).fragment) for link in page.links)
