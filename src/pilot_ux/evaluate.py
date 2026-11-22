"""Score the tool against a known-issue list: recall, false positives, stale (already fixed) issues."""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

import yaml

from . import agents
from .config import Study
from .prompts import render

MATCH_SCHEMA = {"type": "object", "required": ["truth_matches", "issue_labels"], "properties": {
    "truth_matches": {"type": "array", "items": {"type": "object", "required": ["truth_id", "issue_id"], "properties": {
        "truth_id": {"type": "string"}, "issue_id": {"type": ["string", "null"]}}}},
    "issue_labels": {"type": "array", "items": {"type": "object", "required": ["issue_id", "label", "plausible"], "properties": {
        "issue_id": {"type": "string"}, "label": {"type": "string", "enum": ["matches_truth", "stale", "novel"]},
        "plausible": {"type": "boolean"}}}}}}

HUMAN_LABELS = ("real", "hallucinated", "taste", "prototype_gap", "stale")
FIELDS = ["issue_id", "title", "severity", "prototype_gap", "auto_label", "auto_plausible", "human_label", "note"]


def final_label(row: dict) -> str:
    if row.get("human_label"):
        return row["human_label"].strip()
    if str(row["prototype_gap"]).lower() == "true":
        return "prototype_gap"
    if row["auto_label"] == "stale":
        return "stale"
    if row["auto_label"] == "matches_truth":
        return "real"
    return "real" if str(row.get("auto_plausible")).lower() == "true" else "hallucinated"


def compute_metrics(truth: dict, matches: dict[str, str | None], rows: list[dict]) -> dict:
    in_scope = [t["id"] for t in truth.get("issues", []) if t.get("in_scope", True)]
    matched = [t for t in in_scope if matches.get(t)]
    labels = {r["issue_id"]: final_label(r) for r in rows}
    non_gap = [i for i, l in labels.items() if l != "prototype_gap"]
    c = Counter(labels[i] for i in non_gap)
    n = len(non_gap) or 1
    return {"recall": len(matched) / len(in_scope) if in_scope else float("nan"),
            "in_scope": len(in_scope), "matched_in_scope": len(matched),
            "matched_ids": matched, "missed_ids": [t for t in in_scope if t not in matched],
            "non_gap_issues": len(non_gap), "labels": dict(c),
            "false_positive_rate": c["hallucinated"] / n, "taste_rate": c["taste"] / n, "stale_rate": c["stale"] / n,
            "precision_real": c["real"] / n,
            "stale_matched": [t["id"] for t in truth.get("stale", []) if matches.get(t["id"])]}


async def run(study: Study, out: Path, truth_path: Path, labels_path: Path | None = None) -> dict:
    truth = yaml.safe_load(Path(truth_path).read_text())
    issues = json.loads((out / "issues.json").read_text())
    ed = out / "eval"
    ed.mkdir(exist_ok=True)
    mpath = ed / "matches.json"
    if mpath.exists():
        res = json.loads(mpath.read_text())
    else:
        tlist = [{"id": t["id"], "text": t["text"]} for t in truth.get("issues", [])] + \
                [{"id": t["id"], "text": t["text"], "stale": True} for t in truth.get("stale", [])]
        ilist = [{"id": i["id"], "title": i["title"], "description": i["description"],
                  "evidence": [e["quote"] for e in i["evidence"][:3]], "prototype_gap": i["prototype_gap"]} for i in issues]
        res = await agents.ask_json(study, "matcher", "You are a rigorous usability research analyst.",
                                    render("matcher", truth=json.dumps(tlist, ensure_ascii=False),
                                           issues=json.dumps(ilist, ensure_ascii=False)), MATCH_SCHEMA)
        mpath.write_text(json.dumps(res, indent=1))
    matches = {m["truth_id"]: m["issue_id"] for m in res["truth_matches"]}
    auto = {l["issue_id"]: l for l in res["issue_labels"]}
    labels_path = Path(labels_path) if labels_path else ed / "labels.csv"
    if labels_path.exists():
        rows = list(csv.DictReader(labels_path.open()))
    else:
        rows = [{"issue_id": i["id"], "title": i["title"], "severity": i["severity"], "prototype_gap": i["prototype_gap"],
                 "auto_label": auto.get(i["id"], {}).get("label", "novel"),
                 "auto_plausible": auto.get(i["id"], {}).get("plausible", ""), "human_label": "", "note": ""}
                for i in issues]
        with labels_path.open("w", newline="") as f:
            w = csv.DictWriter(f, FIELDS)
            w.writeheader()
            w.writerows(rows)
    bad = [r["human_label"] for r in rows if r.get("human_label") and r["human_label"] not in HUMAN_LABELS]
    if bad:
        raise ValueError(f"unknown human_label values {set(bad)}; use one of {HUMAN_LABELS}")
    m = compute_metrics(truth, matches, rows)
    m["labelled_by"] = "human" if any(r.get("human_label") for r in rows) else "auto (LLM matcher)"
    (ed / "metrics.json").write_text(json.dumps(m, indent=1))
    return m
