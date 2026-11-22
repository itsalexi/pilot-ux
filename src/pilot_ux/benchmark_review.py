"""Shuffle and mask session findings for a first-pass review, then attribute supported issues."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import secrets
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image

from .device_mcp import TOOL_NAMES
from .outcomes import write_json

PUBLIC = ["candidate_id", "goal", "screen", "element", "description", "actions", "evidence"]
REVIEW = ["decision", "canonical_id", "reviewer_kind", "reviewer", "reason"]
DECISIONS = {"supported", "fixture_gap", "unsupported", "preference"}
PROVENANCE = {"human", "ai", "mixed"}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def recording_signature(directory):
    return {name: digest(path) if (path := directory / name).is_file() else None
            for name in ("outcome.json", "steps.jsonl", "findings.json")}


def planned_sessions(manifest):
    sessions = manifest["sessions"]
    if not sessions:
        raise ValueError("benchmark manifest contains no planned sessions")
    cells, ids = defaultdict(list), set()
    for s in sessions:
        rid = s["run_id"]
        if not isinstance(rid, str) or not rid or Path(rid).name != rid or rid in {".", ".."} or rid in ids:
            raise ValueError("benchmark manifest has an invalid or duplicated run ID")
        ids.add(rid)
        if s["arm"] not in {"generic", "persona"} or type(s["singleton"]) is not bool:
            raise ValueError(f"{rid}: invalid benchmark arm or singleton marker")
        if not isinstance(manifest["tasks"].get(s["task"]), str) or not manifest["tasks"][s["task"]].strip():
            raise ValueError(f"{rid}: the planned task has no neutral goal")
        cells[(s["task"], s["panel"])].append(s)
    for key, group in cells.items():
        generic = [s for s in group if s["arm"] == "generic"]
        persona = [s for s in group if s["arm"] == "persona"]
        ordered_slots = list(range(1, len(generic) + 1))
        if (not generic or any(sorted(s["slot"] for s in arm) != ordered_slots for arm in (generic, persona))
                or sum(s["singleton"] for s in generic) != 1 or any(s["singleton"] for s in persona)):
            raise ValueError(f"{key}: expected equal planned arms and one prespecified generic singleton")
    return sessions


def safe_action(record):
    tool, args = record["tool"], record["args"]
    if tool not in TOOL_NAMES or not isinstance(args, dict):
        raise ValueError("unknown or malformed recorded action")
    if tool == "tap":
        if any(type(args.get(key)) is not int for key in ("x", "y")):
            raise ValueError("missing or malformed tap coordinates")
        return f"tap ({args['x']}, {args['y']})"
    return tool


def export_frames(recording, frames, cited, destination):
    if not cited or not isinstance(cited, list) or any(type(step) is not int or step < 0 for step in cited):
        return {}, [], False
    files, actions, complete = {}, [], True
    for ordinal, step in enumerate(dict.fromkeys(cited), 1):
        try:
            action = safe_action(frames[step])
        except (KeyError, TypeError, ValueError):
            action, complete = "unavailable", False
        actions.append(f"{ordinal:02d} {action}")
        for phase, index in (("before", step - 1), ("after", step)):
            if index < 0:
                continue
            try:
                rel = frames[index]["shot"]
                path = (recording / rel).resolve()
                if not path.is_relative_to(recording) or not path.is_file():
                    raise ValueError("missing recorded screenshot")
                dest = destination / f"{ordinal:02d}-{phase}.png"
                with Image.open(path) as src:
                    if src.format != "PNG":
                        raise ValueError("expected a PNG recording")
                    pixels = src.convert("RGB")
                    pixels.info.clear()
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    pixels.save(dest, "PNG")
                files[f"{destination.name}/{dest.name}"] = digest(dest)
            except (OSError, KeyError, TypeError, ValueError):
                complete = False
    return files, actions, complete


def validated_frames(folder: Path, outcome: dict) -> dict[int, dict]:
    """Validate sufficient first-party recording evidence for annotation and a canary retry."""
    try:
        steps = [json.loads(line) for line in (folder / "steps.jsonl").read_text().splitlines() if line.strip()]
        if not steps or type(outcome.get("steps")) is not int or len(steps) != outcome["steps"]:
            raise ValueError("outcome and transcript step counts differ")
        for index, row in enumerate(steps):
            if type(row["i"]) is not int or row["i"] != index:
                raise ValueError("transcript steps are missing or out of order")
            if not isinstance(row.get("thought"), str) or not row["thought"].strip() or type(row.get("changed")) is not bool:
                raise ValueError("transcript is missing a spoken observation or screen-change record")
            safe_action(row)
            shot = (folder / row["shot"]).resolve()
            if not shot.is_relative_to(folder.resolve()) or not shot.is_file():
                raise ValueError("recording has missing or invalid frames")
        return {row["i"]: row for row in steps}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise ValueError(f"{folder.name}: invalid recorded transcript ({error})") from error


def session_inputs(folder):
    try:
        outcome = read(folder / "outcome.json")
        status = outcome.get("status")
        if status not in {"done", "gave_up", "out_of_patience", "abandoned"}:
            return [], {}, "no completed session"
        if outcome.get("contaminated") is not False or outcome.get("canary_error"):
            return [], {}, "contaminated or missing canary result"
        findings = read(folder / "findings.json")["findings"]
        if not isinstance(findings, list) or not all(isinstance(f, dict) for f in findings):
            raise ValueError("invalid annotation")
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return [], {}, "missing or unreadable outcome or annotation"
    try:
        error = "abandoned session; partial exposure only" if status == "abandoned" else None
        return findings, validated_frames(folder, outcome), error
    except ValueError:
        return findings, {}, "missing or unreadable transcript or frames"


def masked_text(value, aliases, quote):
    text = value if isinstance(value, str) else ""
    if isinstance(quote, str) and quote:
        text = re.sub(re.escape(quote), "[masked]", text, flags=re.IGNORECASE)
    for sensitive in aliases:
        text = re.sub(r"(?<!\w)" + re.escape(sensitive) + r"(?!\w)", "[masked]", text, flags=re.IGNORECASE)
    return text


def export_review(benchmark_dir: Path, review_dir: Path) -> Path:
    """Write a portable reviewer-only directory. The allocation key stays under the benchmark root."""
    base, dest = Path(benchmark_dir).resolve(), Path(review_dir).resolve()
    if base.is_relative_to(dest) or dest.is_relative_to(base / "study") or dest.is_relative_to(base / ".review-maps"):
        raise ValueError("choose a review directory separate from the private recordings and allocation key")
    if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
        raise ValueError("export requires a fresh or empty review directory to preserve existing labels")
    source = base / "benchmark.json"
    manifest = read(source)
    schedule = planned_sessions(manifest)
    aliases = {s["run_id"] for s in schedule}
    aliases.update(s["source_card"] for s in schedule if s.get("source_card"))
    lock = base / "study/study.lock.json"
    if lock.is_file():
        for person in read(lock).get("study", {}).get("personas", []):
            aliases.update(value for k in ("id", "name") if (value := person.get(k)) and len(value) >= 3)
    aliases = sorted(aliases, key=len, reverse=True)
    token = secrets.token_hex(16)
    key = {"manifest_sha256": digest(source), "candidates": {}, "session_errors": {}, "recording_signatures": {}}
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest.parent) as staging:
        bundle = Path(staging) / "bundle"
        bundle.mkdir()
        rows = []
        for session in schedule:
            rid = session["run_id"]
            recording = base / "study/runs" / rid
            if not recording.resolve().is_relative_to(base / "study/runs"):
                raise ValueError("benchmark recording points outside the study directory")
            signature = recording_signature(recording)
            findings, frames, error = session_inputs(recording)
            if error:
                key["session_errors"][rid] = error
            for idx, finding in enumerate(findings):
                cid = secrets.token_hex(12)
                files, actions, valid = export_frames(recording, frames, finding.get("steps"), bundle / cid)
                visible = {k: masked_text(finding.get(k), aliases, finding.get("evidence_quote")) for k in
                           ("screen", "element", "description")}
                visible.update(candidate_id=cid, goal=masked_text(manifest["tasks"][session["task"]], aliases, None),
                               actions=" | ".join(actions), evidence=" | ".join(files))
                rows.append(visible)
                key["candidates"][cid] = {"run_id": rid, "finding_index": idx, "steps": finding.get("steps"), "public": visible,
                                          "files": files, "valid": valid and bool(visible["description"].strip())}
            if recording_signature(recording) != signature:
                raise ValueError("benchmark recording changed during export; retry on a stable collection")
            key["recording_signatures"][rid] = signature
        secrets.SystemRandom().shuffle(rows)
        with (bundle / "review.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, PUBLIC + REVIEW)
            writer.writeheader()
            writer.writerows(rows)
        write_json(bundle / "bundle.json", {"id": token, "instructions": [
            "Open the PNG paths for each candidate in order. Only post-action frames exist for initial observations.",
            "Fill decision with supported, fixture_gap, unsupported, or preference. Leave unreviewed rows blank.",
            "For supported rows, assign the same canonical_id to every instance of the same underlying issue.",
            "For each decision give reviewer_kind (human, ai or mixed), reviewer name/model, and a reason from the images.",
        ]})
        write_json(base / ".review-maps" / f"{token}.json", key)
        os.replace(bundle, dest)
    return dest / "review.csv"


def load_reviews(dest, key):
    rows = {}
    with (dest / "review.csv").open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if set(reader.fieldnames or ()) != set(PUBLIC + REVIEW):
            raise ValueError("review.csv has missing or unexpected columns")
        for row in reader:
            cid = row["candidate_id"]
            candidate = key["candidates"].get(cid)
            if not candidate or cid in rows:
                raise ValueError("unknown or repeated candidate ID in review.csv")
            if any(row[name] != candidate["public"][name] for name in PUBLIC):
                raise ValueError(f"{cid}: the masked candidate fields have changed")
            fields = {k: (row[k] or "").strip() for k in REVIEW}
            choice = fields["decision"]
            if choice:
                if choice not in DECISIONS or fields["reviewer_kind"] not in PROVENANCE:
                    raise ValueError(f"{cid}: invalid decision or reviewer kind")
                if not fields["reason"] or not fields["reviewer"]:
                    raise ValueError(f"{cid}: a decision needs a reviewer and evidence-grounded reason")
                if (choice == "supported") != bool(fields["canonical_id"]):
                    raise ValueError(f"{cid}: canonical_id is required only for supported issues")
            rows[cid] = fields
    return rows


def initial_state(manifest):
    target = manifest.get("study", {}).get("target", {}).get("kind", "unrecorded")
    if target == "url":
        scope = ("Each session opens a fresh browser context. Accounts, shared records and other server state can "
                 "carry over between arms. The fixed build identifier does not verify a reset.")
    elif target == "ios":
        scope = ("The runner requests a clean simulator app install per session. Backend accounts and shared data "
                 "can survive reinstalls. Server reset and equivalent starting data have not been verified.")
    elif target in {"static", "proto"}:
        scope = ("The runner resets the browser/device context around the local fixture. State in any external "
                 "service the fixture may contact was not checked.")
    else:
        scope = "Initial-state isolation cannot be established from this manifest."
    return {"target_kind": target, "server_state": "unverified", "scope": scope}


def score_review(benchmark_dir: Path, review_dir: Path) -> dict:
    """Score only reviewed, supported candidates. Withhold arm exclusivity whenever input or review is incomplete."""
    base, dest = Path(benchmark_dir).resolve(), Path(review_dir).resolve()
    source = base / "benchmark.json"
    manifest = read(source)
    sessions = planned_sessions(manifest)
    token = read(dest / "bundle.json")["id"]
    if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{32}", token):
        raise ValueError("invalid masked bundle ID")
    key = read(base / ".review-maps" / f"{token}.json")
    if key["manifest_sha256"] != digest(source):
        raise ValueError("the planned benchmark changed after review export")
    for rid, signature in key.get("recording_signatures", {}).items():
        if recording_signature(base / "study/runs" / rid) != signature:
            raise ValueError("benchmark recordings or annotations changed after export; review a fresh bundle")
    reviews = load_reviews(dest, key)
    hits, pending, damaged = defaultdict(set), Counter(), Counter()
    reviewed, reviewers, decisions = [], Counter(), Counter()
    for cid, candidate in key["candidates"].items():
        rid = candidate["run_id"]
        record = reviews.get(cid, {})
        choice = record.get("decision")
        valid = candidate["valid"] and all(
            (dest / path).is_file() and digest(dest / path) == expected for path, expected in candidate["files"].items())
        if not valid:
            damaged[rid] += 1
            if choice == "supported":
                raise ValueError(f"{cid}: cannot credit a claim with missing or changed cited frames")
        if not choice:
            pending[rid] += 1
            continue
        decisions[choice] += 1
        reviewers[(record["reviewer_kind"], record["reviewer"])] += 1
        reviewed.append({"candidate_id": cid, "run_id": rid, "finding_index": candidate["finding_index"],
                         "steps": candidate["steps"], **record})
        if choice == "supported":
            hits[rid].add(record["canonical_id"])

    cells = defaultdict(list)
    for s in sessions:
        cells[(s["task"], s["panel"])].append(s)
    panels = []
    for (task, panel), group in sorted(cells.items()):
        arms = {arm: [s["run_id"] for s in group if s["arm"] == arm] for arm in ("generic", "persona")}
        singleton = next(s["run_id"] for s in group if s["singleton"])
        generic, persona = (set().union(*(hits[r] for r in arms[arm])) for arm in ("generic", "persona"))
        rids = [s["run_id"] for s in group]
        errors = {r: key["session_errors"][r] for r in rids if r in key["session_errors"]}
        n_pending = sum(pending[r] for r in rids)
        n_bad = sum(damaged[r] for r in rids)
        complete = not (errors or n_pending or n_bad)
        counts = {"singleton": sorted(hits[singleton]), "generic": sorted(generic), "persona": sorted(persona)}
        panels.append({"task": task, "panel": panel, "complete": complete, "attribution": "descriptive_only", "session_errors": errors,
                       "planned_sessions": len(rids), "pending_candidates": n_pending, "invalid_evidence": n_bad,
                       **counts, "unique_counts": {arm: len(ids) for arm, ids in counts.items()},
                       "generic_only": sorted(generic-persona) if complete else None,
                       "persona_only": sorted(persona-generic) if complete else None,
                       "shared": sorted(generic & persona) if complete else None,
                       "mean_single_generic": sum(len(hits[r]) for r in arms["generic"]) / len(arms["generic"]) if complete else None})
    result = {"bundle_id": token, "manifest_sha256": key["manifest_sha256"], "panels": panels,
              "candidates": len(key["candidates"]),
              "reviewed_candidates": len(reviewed), "pending_candidates": sum(pending.values()),
              "invalid_evidence": sum(damaged.values()), "incomplete_sessions": len(key["session_errors"]),
              "decisions": dict(decisions), "reviewers": [
                  {"kind": kind, "reviewer": reviewer, "decisions": n} for (kind, reviewer), n in sorted(reviewers.items())],
              "review_records": reviewed, "reachability": "unassessed", "initial_state": initial_state(manifest),
              "interpretation": "Sets count canonical issues supported by the masked reviewers in these recordings. "
              "An arm-only observation does not establish that other sessions reached the control or missed it there. "
              "A difference also cannot establish the effect of a persona card when starting application state is unverified. "
              "Incomplete panels report lower bounds only."}
    from .benchmark_usage import summarize_usage
    result["usage"] = summarize_usage(base)
    write_json(base / "benchmark-score.json", result)
    return result
