"""Markdown + self-contained HTML report. Problems only; no praise section by design."""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

import numpy as np

from .analyze import effective_status, load_json, run_dirs
from .config import Study

SEV = {0: "not a problem", 1: "cosmetic", 2: "minor", 3: "major", 4: "catastrophe"}
CONSTRUCT_LABEL = {"ease": "Ease", "trust": "Trust", "use_intent": "Would use again", "pay_intent": "Would pay"}
STATUS_ORDER = ["success", "failed_claim", "gave_up", "out_of_patience", "abandoned", "error"]


def gather(study: Study, out: Path) -> dict:
    lock = load_json(out / "study.lock.json") or {}
    scheduled = Study(**lock["study"]) if lock.get("study") else study
    runs = []
    session_roles = {"persona": set(), "interview": set()}
    for spec, rd in run_dirs(study, out):
        o = load_json(rd / "outcome.json")
        for role, labels in session_roles.items():
            backend = scheduled.backend_for(role, spec.n)
            if role == "persona":
                backend = o.get("backend") or backend
            # The lock records default role models. Run-number overrides can select another backend.
            pinned = lock.get("models", {}).get(role, "")
            model = o.get("model") if role == "persona" else None
            if not model and backend == scheduled.backend_for(role) and pinned:
                model = pinned.removeprefix(f"{backend}:")
            if not model and lock and backend == "codex":
                model = scheduled.codex_models.get(role) or scheduled.codex_model or "unrecorded"
            labels.add(f"{backend}:{model or scheduled.model_for(role, backend)}")
        runs.append({"id": spec.id, "persona": spec.persona.id, "task": spec.task.id, "outcome": o,
                     "status": effective_status(o, load_json(rd / "verdict.json")),
                     "verdict": load_json(rd / "verdict.json"), "ssr": load_json(rd / "ssr.json"),
                     "interview": load_json(rd / "interview.json")})
    issues = load_json(out / "issues.json") or []
    reviews_path = out / "eval" / "labels.csv"
    if reviews_path.is_file():
        with reviews_path.open(encoding="utf-8", newline="") as labels_file:
            labels = {r["issue_id"]: r for r in csv.DictReader(labels_file) if r.get("human_label")}
        for issue in issues:
            row = labels.get(issue["id"])
            if row and row["title"] == issue["title"]:
                issue["review_label"] = row["human_label"]
                issue["review_note"] = row.get("note", "")
    def classification(issue):
        return issue.get("review_label") or ("prototype_gap" if issue["prototype_gap"] else "real")
    real = [i for i in issues if classification(i) == "real"]
    real.sort(key=lambda i: (-i["severity"] * i["frequency"], -i["severity"]))
    gaps = [i for i in issues if classification(i) == "prototype_gap"]
    excluded = [i for i in issues if classification(i) not in {"prototype_gap", "real"}]
    models = dict(lock.get("models", {}))
    models.update({role: ", ".join(sorted(labels)) for role, labels in session_roles.items() if labels})
    from .analyze import agreement
    return {"runs": runs, "issues": real, "gaps": gaps, "agreement": agreement(study, out),
            "lock": lock, "models": models, "metrics": load_json(out / "eval/metrics.json"),
            "excluded": excluded, "recheck": load_json(out / "recheck.json")}


def _ssr_agg(runs: list[dict], construct: str, persona: str | None = None):
    ps = [r["ssr"]["scores"][construct]["pmf"] for r in runs
          if r["ssr"] and construct in r["ssr"]["scores"] and (persona is None or r["persona"] == persona)]
    return (np.mean(ps, axis=0), len(ps)) if ps else (None, 0)


def _naive(runs, construct, persona=None):
    return [r["ssr"]["naive"][construct] for r in runs
            if r["ssr"] and construct in r["ssr"].get("naive", {}) and (persona is None or r["persona"] == persona)]


def build(study: Study, out: Path) -> tuple[Path, Path]:
    out.mkdir(parents=True, exist_ok=True)
    d = gather(study, out)
    md = render_md(study, out, d)
    html = render_html(study, out, d)
    (out / "report.md").write_text(md)
    (out / "report.html").write_text(html)
    return out / "report.md", out / "report.html"


def _task_table(study, runs):
    rows = []
    for t in study.tasks:
        rs = [r for r in runs if r["task"] == t.id]
        c = Counter(r["status"] for r in rs)
        rows.append((t, len(rs), c))
    return rows


def render_md(study: Study, out: Path, d: dict) -> str:
    runs = d["runs"]
    L = [f"# ux-swarm report: {study.name}", "",
         f"> Synthetic users ({len(study.personas)} personas × {len(study.tasks)} tasks × {study.runs} runs, "
         f"persona models `{d['models'].get('persona', 'unrecorded')}`). Use this to triage, then test with real people. "
         f"Agents are more patient, literal and polite than humans; trust and emotion findings are weakest.", "",
         "## Task outcomes", "", "| Task | Verified success | Claimed but not verified | Gave up | Out of patience | Other |",
         "|---|---|---|---|---|---|"]
    for t, n, c in _task_table(study, runs):
        other = n - sum(c[k] for k in ("success", "failed_claim", "gave_up", "out_of_patience"))
        L.append(f"| {t.goal} | {c['success']}/{n} | {c['failed_claim']} | {c['gave_up']} | {c['out_of_patience']} | {other} |")
    L += ["", "### Where people gave up", ""]
    quits = [r for r in runs if r["status"] in ("gave_up", "out_of_patience")]
    for r in quits[:30]:
        reason = r["outcome"].get("reason") or "ran out of patience"
        L.append(f"- **{r['persona']}** ({r['task']}, step {r['outcome'].get('steps')}): \"{reason}\"")
    if not quits:
        L.append("- nobody quit")
    L += ["", f"## Issues ({len(d['issues'])}), sorted by severity × frequency", ""]
    for i in d["issues"]:
        sev = int(round(i["severity"]))
        ev = i["evidence"][0]
        L += [f"### {i['id']}. {i['title']}",
              f"**Severity {i['severity']:g} ({SEV[sev]})** · hit by {len(i['personas'])}/{len(study.personas)} personas "
              f"({', '.join(i['personas'])}) in {len(i['runs'])} runs · tasks: {', '.join(i['tasks'])}"
              + (f" · ⚠ {i['agent_misread_share']:.0%} of reports flagged as possible agent misreading" if i.get("agent_misread_share") else ""),
              "", i["description"], "", f"> \"{ev['quote']}\" ({ev['run']}, step {', '.join(map(str, ev['steps']))})", "",
              f"**Suggested fix:** {i['suggested_fix']}", ""]
    L += ["## Attitudes (SSR distributions)", "",
          "Free-text answers given in character after each task, mapped to 1–5 distributions by semantic similarity "
          "to anchor statements (Maier et al. 2025). Bars show the probability mass on 1…5. The `asked for a number` "
          "column is the naive 1–5 the same persona gave directly; compare its spread.", "",
          "| Question | Persona | SSR distribution 1→5 | SSR mean | Asked for a number (mean, sd) |", "|---|---|---|---|---|"]
    for c in CONSTRUCT_LABEL:
        for p in [None] + [x.id for x in study.personas]:
            agg, n = _ssr_agg(runs, c, p)
            if agg is None:
                continue
            nv = _naive(runs, c, p)
            bars = " ".join(f"{v:.2f}" for v in agg)
            L.append(f"| {CONSTRUCT_LABEL[c] if p is None else ''} | {p or '**all**'} | {bars} | "
                     f"{float(agg @ np.arange(1, 6)):.2f} | {np.mean(nv):.2f}, {np.std(nv):.2f} |" if nv else
                     f"| {CONSTRUCT_LABEL[c] if p is None else ''} | {p or '**all**'} | {bars} | {float(agg @ np.arange(1, 6)):.2f} | – |")
    sus = [r["ssr"]["sus"]["median"] for r in runs if r["ssr"] and r["ssr"].get("sus")]
    if sus:
        L += ["", f"**SUS (via SSR):** median of run medians {np.median(sus):.1f}, "
                  f"range {min(sus):.1f}–{max(sus):.1f} across {len(sus)} runs (68 ≈ average product)."]
    closes = [(r["persona"], r["interview"]["answers"].get("close_trigger")) for r in runs if r["interview"]]
    if closes:
        L += ["", "### What would make them close the app", ""]
        seen = set()
        for p, q in closes:
            if q and p not in seen:
                seen.add(p)
                L.append(f"- **{p}:** \"{q}\"")
    if d["gaps"]:
        L += ["", "## Prototype gaps (not counted as usability problems)", ""]
        for g in d["gaps"]:
            L.append(f"- {g['title']} ({len(g['runs'])} runs)")
    if d.get("excluded"):
        L += ["", "## Other reviewed observations", ""]
        L.extend(f"- {i['title']} ({i['review_label']})" for i in d["excluded"])
    ag = d["agreement"]
    contaminated = sum(1 for r in runs if r["outcome"].get("contaminated"))
    overturned = sum(1 for r in runs if r["status"] == "failed_claim")
    claimed = sum(1 for r in runs if r["outcome"].get("status") == "done")
    L += ["", "## Validity", "",
          f"- Runs: {len(runs)} · errors: {sum(r['status'] == 'error' for r in runs)} · "
          f"leak canary flagged: {contaminated}",
          f"- Verifier overturned {overturned}/{claimed} claimed successes",
          f"- Run-to-run agreement (same persona × task): issue-set Jaccard {ag['mean_jaccard']:.2f}, "
          f"same outcome {ag['outcome_agreement']:.2f}, Fleiss κ (outcome) {ag['fleiss_kappa_outcome']:.2f}",
          f"- Models: {json.dumps(d['models'])} · embedder `{study.embedder}`"]
    version = d["lock"].get("claude_version")
    if version and any("claude:" in models for models in d["models"].values()):
        L.append(f"- Claude CLI: {version}")
    if d["metrics"]:
        m = d["metrics"]
        L += [f"- Against known issues: recall {m['recall']:.0%} ({m['matched_in_scope']}/{m['in_scope']}), "
              f"false-positive rate {m['false_positive_rate']:.0%}, stale-issue rate {m['stale_rate']:.0%}"]
    if d.get("recheck"):
        check = d["recheck"]
        L += ["", "## Before and after", "", f"{check['comparable_sessions']} comparable sessions."]
        for task, phases in check.get("task_outcomes", {}).items():
            counts = [", ".join(f"{n} {status}" for status, n in phases.get(phase, {}).items())
                      for phase in ("before", "after")]
            L.append(f"- {task} · {counts[0]} before → {counts[1]} after")
        for issue in check["issues"]:
            L += ["", f"### {issue['id']} · {issue['title']}", "", issue["status"]]
            for obs in issue["observations"]:
                L.append(f"- {obs['result']} · {obs['note']} (reviewer: {obs['reviewer']}, "
                         f"baseline {obs['before_run']} step ID {obs['before_step']} → "
                         f"current {obs['after_run']} step ID {obs['after_step']})")
    L += ["", "## Limitations", "",
          "- Synthetic users are not users. Use these findings to decide what to test with real people, not to skip that.",
          "- Agents read screenshots; tiny text, motion, haptics, sound and real-world context (noise, a waiting barkada) are not felt.",
          "- Persona language registers (e.g. Taglish) test the copy, not real cultural behaviour.",
          "- SSR distributions depend on the anchor statements; compare studies only when anchors are identical."]
    return "\n".join(L) + "\n"


def render_html(study: Study, out: Path, d: dict) -> str:
    from .report_web import render
    return render(study, out, d)
