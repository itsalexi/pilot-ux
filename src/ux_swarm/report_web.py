"""Render a portable study report with session playback and step-level evidence."""

from __future__ import annotations

import base64
import html
import io
import json
import math
from pathlib import Path
from urllib.parse import urlencode

import numpy as np
from PIL import Image

from .config import Study
from .replay import collect_replay, render_replay
from .report import CONSTRUCT_LABEL, _naive, _ssr_agg, _task_table
from .ssr import SUS_ITEMS


def esc(value) -> str:
    return html.escape(str(value))


def table(headings, rows):
    header = "".join(f'<th scope="col">{esc(label)}</th>' for label in headings)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return f'<div class="scroll"><table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table></div>'


def count_text(n, noun):
    return f"{n} {noun}" + ("" if n == 1 else "s")


def percentage(value):
    return f"{value:.0%}" if value is not None and math.isfinite(value) else "Unavailable"


class Evidence:
    def __init__(self, replay):
        self.replay = replay
        self.steps = {session["id"]: {step["i"]: step for step in session["steps"]}
                      for session in replay["sessions"]}
        self.ordinals = {run: {step_id: n for n, step_id in enumerate(steps, start=1)}
                         for run, steps in self.steps.items()}
        self.thumbnails = {}

    def link(self, run, step, label):
        if run not in self.steps or (step is not None and step not in self.steps[run]):
            return esc(label)
        params = {"session": run}
        if step is not None:
            params["step"] = step
        return f'<a href="#{esc(urlencode(params))}">{esc(label)}</a>'

    def cite(self, ev):
        run = ev["run"]
        steps = [i for i in ev.get("steps", []) if i in self.steps.get(run, {})]
        if not steps:
            return self.link(run, None, run)
        links = [self.link(run, i, f"Step {self.ordinals[run][i]}") for i in steps]
        return self.link(run, steps[0], run) + " · " + ", ".join(links)

    def thumbnail(self, evidence, caption=None, linked=True):
        for ev in evidence:
            for step in ev.get("steps", []):
                row = self.steps.get(ev["run"], {}).get(step, {})
                index = row.get("image")
                if index is None:
                    continue
                if index not in self.thumbnails:
                    raw = base64.b64decode(self.replay["images"][index].partition(",")[2])
                    with Image.open(io.BytesIO(raw)) as img:
                        img.thumbnail((240, 280))
                        buf = io.BytesIO()
                        img.convert("RGB").save(buf, "JPEG", quality=76)
                    self.thumbnails[index] = base64.b64encode(buf.getvalue()).decode("ascii")
                url = esc(urlencode({"session": ev["run"], "step": step}))
                ordinal = self.ordinals[ev["run"]][step]
                content = (f'<img src="data:image/jpeg;base64,{self.thumbnails[index]}" alt="Screen after step {ordinal}">'
                           f'<span>{esc(caption or "Replay")} · Step {ordinal}{" ↗" if linked else ""}</span>')
                if linked:
                    return f'<a class="shot" href="#{url}" aria-label="Replay {esc(ev["run"])} at step {ordinal}">{content}</a>'
                return f'<figure class="shot">{content}</figure>'
        return ""


def issue_card(issue, evidence, people, compact=False):
    evs = issue.get("evidence", [])
    title = esc(issue["title"])
    reach = f'{count_text(len(issue["personas"]), "persona")} · {count_text(len(issue["runs"]), "session")}'
    meta = (f'Severity {issue["severity"]:g}/4 · {len(issue["personas"])}/{people} personas · '
            f'{esc(", ".join(issue["tasks"]))} · {esc(issue["id"])}')
    body = [f'<p class="meta">{meta}</p>', f'<p>{esc(issue["description"])}</p>']
    if evs:
        body.append(f'<blockquote>{esc(evs[0]["quote"])}</blockquote><p class="citation">{evidence.cite(evs[0])}</p>')
    if issue.get("suggested_fix"):
        body.append(f'<p><b>Suggested change</b> &nbsp; {esc(issue["suggested_fix"])}</p>')
    if issue.get("agent_misread_share"):
        body.append(f'<p class="note">Annotators flagged a possible screenshot misread in '
                    f'{percentage(issue["agent_misread_share"])} of contributing observations.</p>')
    if issue.get("review_note"):
        body.append(f'<details><summary>Review note</summary><p>{esc(issue["review_note"])}</p></details>')
    if len(evs) > 1:
        items = "".join(f'<li>{evidence.cite(ev)}<p>{esc(ev["quote"])}</p></li>' for ev in evs[1:])
        body.append(f'<details><summary>More evidence ({len(evs) - 1})</summary><ul>{items}</ul></details>')
    if compact:
        return f'<details class="observation"><summary>{title}</summary>{"".join(body)}</details>'
    return (f'<details class="finding" id="finding-{esc(issue["id"])}">'
            f'<summary><span class="finding-name">{title}</span><span class="reach">{reach}</span></summary>'
            f'<div class="finding-body"><div>{"".join(body)}</div>{evidence.thumbnail(evs)}</div></details>')


def attitudes(study, runs):
    rows = []
    for key, label in CONSTRUCT_LABEL.items():
        for person in [None, *(p.id for p in study.personas)]:
            pmf, n = _ssr_agg(runs, key, person)
            if pmf is None:
                continue
            nums = _naive(runs, key, person)
            dist = " / ".join(f"{v:.0%}" for v in pmf)
            rows.append([esc(label), esc(person or "All"), str(n), dist, f"{pmf @ np.arange(1, 6):.2f}",
                         f"{np.mean(nums):.2f} ± {np.std(nums):.2f}" if nums else "—"])
    body = ('<p>Free-text interview answers were scored against rating anchors using Semantic Similarity Rating '
            '(SSR). Each distribution shows the share assigned to scores 1 through 5. Direct ratings came from '
            'the same interviews.</p>' +
            table(["Question", "Persona", "Sessions", "SSR distribution (1–5)", "SSR mean", "Direct mean ± SD"], rows)
            if rows else '<p>Attitude scores are unavailable.</p>')
    if study.embedder == "fake" and rows:
        body = '<p class="callout">This study used test embeddings. Its attitude scores are for pipeline testing only.</p>' + body
    sus = [r["ssr"]["sus"]["median"] for r in runs if r["ssr"] and r["ssr"].get("sus")]
    if sus:
        body += (f'<p><b>System Usability Scale</b> &nbsp; Median of session medians {np.median(sus):g}/100. '
                 f'Session medians range from {min(sus):g} to {max(sus):g} across {len(sus)} sessions.</p>')
    return body


def session_list(study, runs, evidence):
    names = {p.id: p.name for p in study.personas}
    body = []
    for run in runs:
        label = STATUS_LABELS.get(run["status"], run["status"])
        summary = (f'{esc(names.get(run["persona"], run["persona"]))} · {esc(run["task"])} '
                   f'· {esc(run["id"].rsplit("__", 1)[-1])}')
        text = [f'<details class="session"><summary>{summary} <span class="status">{esc(label)}</span></summary>']
        if run["id"] in evidence.steps:
            text.append('<p>' + evidence.link(run["id"], None, "Watch session ↗") + '</p>')
        outcome = run["outcome"]
        reason = outcome.get("reason") or outcome.get("summary")
        if reason:
            text.append(f'<blockquote>{esc(reason)}</blockquote>')
        if run.get("verdict"):
            text.append(f'<p><b>Verification</b> &nbsp; {esc(run["verdict"].get("reason", ""))}</p>')
        interview = run["interview"] or {}
        if interview.get("answers"):
            text.append('<dl class="answers">')
            for key, answer in interview["answers"].items():
                question = {"close_trigger": "What would make you close the app?"}.get(key, CONSTRUCT_LABEL.get(key, key))
                if key.startswith("sus_") and key[4:].isdigit() and 1 <= int(key[4:]) <= 10:
                    question = SUS_ITEMS[int(key[4:]) - 1]
                text.append(f'<dt>{esc(question)}</dt><dd>{esc(answer)}</dd>')
            text.append('</dl>')
        text.append('</details>')
        body.append("".join(text))
    return "".join(body) or '<p>No session outcomes have been recorded.</p>'


STATUS_LABELS = {"success": "Verified", "failed_claim": "Unverified claim", "gave_up": "Gave up",
                 "out_of_patience": "Out of patience", "abandoned": "Abandoned", "error": "Error"}


def validity(study, d):
    runs = d["runs"]
    ag = d["agreement"]
    checked = sum(type(r["outcome"].get("contaminated")) is bool for r in runs)
    flagged = sum(r["outcome"].get("contaminated") is True for r in runs)
    claims = sum(r["outcome"].get("status") == "done" for r in runs)
    failed = sum(r["status"] == "failed_claim" for r in runs)
    fmt = lambda x: f"{x:.2f}" if math.isfinite(x) else "Unavailable"
    rows = [["Prior-knowledge canary", f"{flagged} flagged among {checked} checked"],
            ["Claims without verification", f"{failed} of {claims} claimed successes"],
            ["Issue-set agreement (Jaccard)", fmt(ag["mean_jaccard"])],
            ["Outcome agreement", percentage(ag["outcome_agreement"])],
            ["Fleiss’ κ on outcome", fmt(ag["fleiss_kappa_outcome"])],
            ["Session errors", str(sum(r["status"] == "error" for r in runs))]]
    m = d["metrics"]
    if m:
        rows += [["Known-issue recall", f"{percentage(m['recall'])} ({m['matched_in_scope']}/{m['in_scope']})"],
                 ["False-positive rate", percentage(m["false_positive_rate"])],
                 ["Stale-issue rate", percentage(m["stale_rate"])]]
    body = [table(["Measure", "Result"], rows)]
    if d["models"]:
        model_rows = [[esc("Recorded persona models" if role == "persona" else role), f'<code>{esc(name)}</code>']
                      for role, name in d["models"].items()]
        model_rows.append(["Embeddings", f'<code>{esc(study.embedder)}</code>'])
        body.append('<details><summary>Models and embeddings</summary>' + table(["Role", "Model"], model_rows) + '</details>')
    body.append('<h3>Limits of the study</h3><p>These synthetic sessions generate hypotheses to check with people. '
                'Screenshot inputs omit sound, haptics and real-world context. Persona language describes the '
                'simulated speaker. Interview scores depend on the chosen anchors and embedding model.</p>')
    return "".join(body)


def recheck_section(study, recheck, evidence):
    ids = {obs["before_run"] for issue in recheck["issues"] for obs in issue["observations"]}
    baseline = None
    before_dir = Path(recheck.get("before_dir", ""))
    if ids and (before_dir / "study.lock.json").is_file():
        try:
            baseline = Evidence(collect_replay(study, before_dir, sorted(ids)))
        except (OSError, ValueError):
            # A shared copy of a study may lack its original baseline recordings.
            pass
    before = esc(recheck.get("before_version") or "Baseline")
    after = esc(recheck.get("after_version") or "Current study")
    body = [f'<p>{before} → {after} · {esc(recheck["comparable_sessions"])} comparable sessions</p>']
    if recheck.get("task_outcomes"):
        rows = []
        for task, phases in recheck["task_outcomes"].items():
            counts = [", ".join(f'{n} {esc(status)}' for status, n in phases.get(phase, {}).items())
                      for phase in ("before", "after")]
            rows.append([esc(task), *counts])
        body.append(table(["Task", "Baseline outcomes", "Current outcomes"], rows))
    for issue in recheck["issues"]:
        body.append(f'<article><h3>{esc(issue["id"])} · {esc(issue["title"])}</h3><p>{esc(issue["status"])}</p>')
        if issue.get("candidates"):
            body.append('<p>Candidate matches · ' + ", ".join(esc(i["title"]) for i in issue["candidates"]) + '</p>')
        for obs in issue["observations"]:
            before_run, before_step = obs["before_run"], obs["before_step"]
            after_run, after_step = obs["after_run"], obs["after_step"]
            pair = ([baseline.thumbnail([{"run": before_run, "steps": [before_step]}], "Baseline", False)]
                    if baseline else [])
            pair.append(evidence.thumbnail([{"run": after_run, "steps": [after_step]}], "Current"))
            body.append(f'<p><b>{esc(obs["result"])}</b> · {esc(obs["note"])}</p><p class="caption">Reviewer-supplied '
                        f'evidence · {esc(obs["reviewer"])}</p><div class="pair">{"".join(pair)}</div>')
            before_ref = (f"step {baseline.ordinals[before_run][before_step]}"
                          if baseline and before_step in baseline.steps.get(before_run, {})
                          else f"recorded step ID {before_step}")
            body.append(f'<p class="citation">Baseline {esc(before_run)} · {esc(before_ref)}<br>'
                        f'Current {evidence.cite({"run": after_run, "steps": [after_step]})}</p>')
        body.append('</article>')
    return "".join(body)


def task_results(study, runs):
    rows = []
    for task, n, counts in _task_table(study, runs):
        verified = counts["success"]
        other = n - sum(counts[key] for key in ("success", "failed_claim", "gave_up", "out_of_patience"))
        criteria = "".join(f"<li>{esc(item)}</li>" for item in task.success_criteria)
        outcomes = " · ".join(f"{qty} {label}" for qty, label in [
            (verified, "verified"), (counts["failed_claim"], "unverified claims"),
            (counts["gave_up"], "gave up"), (counts["out_of_patience"], "out of patience"), (other, "other outcomes")
        ] if qty) or "No recorded outcomes"
        name = task.id.replace("-", " ").replace("_", " ")
        rows.append(f'<details class="task"><summary><span>{esc(name[:1].upper() + name[1:])}</span>'
                    f'<span class="task-count">{verified} / {n}</span></summary>'
                    f'<div class="task-detail"><p>{esc(task.goal)}</p><p>{esc(outcomes)}</p>'
                    f'<strong>Success criteria</strong><ul>{criteria}</ul></div></details>')
    verified = sum(run["status"] == "success" for run in runs)
    return (f'<section id="tasks" aria-labelledby="task-title"><h2 id="task-title">Task completion</h2>'
            f'<div class="completion"><strong>{verified}</strong><span> / {len(runs)}</span></div>'
            f'<p class="sub">sessions reached a verified goal</p><div class="task-list">{"".join(rows)}</div></section>')


def opening_finding(d, evidence):
    """Lead with a witnessed change when available, otherwise the first ranked finding."""
    check = d.get("recheck")
    if check:
        phases = list(check.get("task_outcomes", {}).values())
        rates = []
        for phase in ("before", "after"):
            verified = sum(row.get(phase, {}).get("verified", 0) for row in phases)
            total = sum(sum(row.get(phase, {}).values()) for row in phases)
            rates.append(f"{verified}/{total}")
        observations = [obs for issue in check["issues"] for obs in issue["observations"]]
        observed = next((obs for obs in observations if obs["result"] == "improved"), None)
        witness = (evidence.link(observed["after_run"], observed["after_step"], "Watch the retest")
                   if observed else "")
        return (f'<div class="focus"><p class="label">Repair recheck</p><h2>Verified completions went '
                f'from {rates[0]} to {rates[1]}.</h2>'
                f'<p class="support">{esc(observed["note"]) if observed else "Compare the recorded task outcomes across builds."}</p>'
                f'<div class="focus-actions">{witness}<a href="#recheck">Compare builds</a></div></div>')
    if not d["issues"]:
        return ('<div class="focus"><p class="label">Study results</p><h2>No product findings recorded.</h2>'
                '<p class="support">Task outcomes and study coverage are available below.</p></div>')
    issue = d["issues"][0]
    for ev in issue.get("evidence", []):
        steps = evidence.steps.get(ev["run"], {})
        cited = [i for i in ev.get("steps", []) if i in steps]
        if cited:
            # Prefer the action where the cited words were actually spoken.
            quote = ev.get("quote", "").strip().casefold()
            step = next((i for i in cited if quote and quote in steps[i]["say"].casefold()), cited[0])
            watch = evidence.link(ev["run"], step, "Watch evidence")
            break
    else:
        watch = ""
    participants = len(issue["personas"])
    impact = f'{count_text(participants, "persona")} encountered this across {count_text(len(issue["runs"]), "session")}.'
    return (f'<div class="focus"><p class="label">Top finding</p><h2>{esc(issue["title"])}</h2>'
            f'<p class="support">{esc(impact)}</p><div class="focus-actions">{watch}'
            f'<a href="#finding-{esc(issue["id"])}">Read finding</a></div></div>')


def render(study: Study, out: Path, d: dict) -> str:
    replay = collect_replay(study, out)
    evidence = Evidence(replay)
    runs = d["runs"]
    people = len(study.personas)
    sections = []
    cards = "".join(issue_card(issue, evidence, people) for issue in d["issues"])
    sections.append(("findings", "Findings", len(d["issues"]), cards or "<p>No product findings are recorded.</p>"))
    if d.get("recheck"):
        sections.append(("recheck", "Before and after", None, recheck_section(study, d["recheck"], evidence)))
    if d["gaps"]:
        sections.append(("gaps", "Prototype gaps", len(d["gaps"]),
                         "".join(issue_card(i, evidence, people, True) for i in d["gaps"])))
    if d.get("excluded"):
        sections.append(("other", "Other reviewed observations", len(d["excluded"]),
                         "".join(issue_card(i, evidence, people, True) for i in d["excluded"])))
    sections += [("sessions", "Sessions and interviews", len(runs), session_list(study, runs, evidence)),
                 ("interviews", "Interview scores", None, attitudes(study, runs)),
                 ("validity", "Study validity", None, validity(study, d))]
    css = Path(__file__).with_name("report.css").read_text(encoding="utf-8")
    name = study.name.replace("-", " ").replace("_", " ")
    title = esc(name[:1].upper() + name[1:])
    player = ""
    if replay["sessions"]:
        script = Path(__file__).with_name("report-player.js").read_text(encoding="utf-8")
        document = json.dumps(render_replay(replay), ensure_ascii=True).replace("<", r"\u003c")
        player = (f'<dialog id="player" aria-label="Session replay"><header><button type="button" '
                  f'id="close-player">‹ &nbsp; Back to report</button></header>'
                  f'<iframe title="Recorded session player" sandbox="allow-scripts"></iframe></dialog>'
                  f'<script id="player-document" type="application/json">{document}</script><script>{script}</script>')
    links = [("overview", "Overview"), ("tasks", "Task completion"),
             *((key, name) for key, name, _, _ in sections)]
    nav = "".join(f'<a href="#{key}">{name}</a>' for key, name in links)
    content = []
    for key, heading, count, body in sections:
        quantity = f'<span class="quantity">{count}</span>' if count is not None else ""
        if key in ("findings","recheck"):
            content.append(f'<section class="report-section" id="{key}"><h2>{heading}{quantity}</h2>'
                           f'<div class="surface">{body}</div></section>')
        else:
            content.append(f'<section class="more" id="{key}"><details><summary>{heading}{quantity}</summary>'
                           f'<div class="more-body">{body}</div></details></section>')
    menu_script = Path(__file__).with_name("report-navigation.js").read_text(encoding="utf-8")
    header = (f'<header class="mast"><div><b>UX Swarm</b><span>Study report</span></div>'
              f'<details id="contents"><summary>Contents</summary><nav aria-label="Report sections">{nav}</nav></details></header>')
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width, initial-scale=1"><title>{title} · Usability study</title>'
            f'<style>{css}</style></head><body>{header}<main id="overview"><div class="heading"><h1 tabindex="-1">{title}</h1>'
            f'<p>{count_text(len(runs),"session")} · {count_text(people,"synthetic persona")} · '
            f'{esc(study.target.fidelity).capitalize()} study</p></div><div class="overview">'
            f'{opening_finding(d, evidence)}{task_results(study,runs)}</div>{"".join(content)}</main>'
            f'{player}<script>{menu_script}</script></body></html>')
