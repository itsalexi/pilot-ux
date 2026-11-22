"""English line for every think-aloud step that wasn't said in English, cached in translations.json."""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

from . import agents
from .config import Study

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["lines"], "properties": {
    "lines": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["k", "en"],
                                         "properties": {"k": {"type": "string"}, "en": {"type": "string"}}}}}}
SYSTEM = "You translate usability-test think-aloud lines into natural, plain English."
PROMPT = """Translate each line below into natural English, keeping the speaker's tone.
If a line is already entirely in English, return an empty string for it.
Keep names, amounts and on-screen labels exactly as written.
Return one entry per key.

{lines}"""
BATCH = 120


def quote_key(quote: str) -> str:
    return hashlib.sha1(quote.strip().encode()).hexdigest()[:10]


def _quotes(out: Path) -> dict[str, str]:
    """Issue quotes, keyed by content: annotators sometimes trim or merge lines, so they get their own translation."""
    p = out / "issues.json"
    issues = json.loads(p.read_text()) if p.exists() else []
    return {f"q#{quote_key(e['quote'])}": e["quote"] for i in issues for e in i.get("evidence", []) if e.get("quote", "").strip()}


def _lines(out: Path) -> dict[str, str]:
    lines = {}
    for rd in sorted((out / "runs").glob("*__*__r*")):
        steps = rd / "steps.jsonl"
        if not steps.exists():
            continue
        for raw in steps.read_text().splitlines():
            if raw.strip():
                s = json.loads(raw)
                said = s.get("thought") or s.get("say") or ""
                if said.strip():
                    lines[f"{rd.name}#{s['i']}"] = said
    return lines


async def translate(study: Study, out: Path, log=print) -> dict[str, dict[str, str]]:
    dest = out / "translations.json"
    got: dict[str, dict[str, str]] = json.loads(dest.read_text()) if dest.exists() else {}
    lines: dict[str, str] = {}
    if not dest.exists():
        lines.update(_lines(out))
    if "_quotes" not in got:
        lines.update(_quotes(out))
    if not lines:
        return got
    keys = list(lines)
    sem = asyncio.Semaphore(max(1, study.concurrency))

    async def batch(ks: list[str]) -> list[dict]:
        body = "\n".join(json.dumps({"k": k, "line": lines[k]}, ensure_ascii=False) for k in ks)
        async with sem:
            res = await agents.ask_json(study, "translator", SYSTEM, PROMPT.format(lines=body), SCHEMA)
        return res.get("lines", [])

    got.setdefault("_quotes", {})
    added = 0
    for part in await asyncio.gather(*(batch(keys[i:i + BATCH]) for i in range(0, len(keys), BATCH))):
        for row in part:
            en = (row.get("en") or "").strip()
            k = row.get("k", "")
            if en and k in lines and en != lines[k].strip():
                run, step = ("_quotes", k[2:]) if k.startswith("q#") else k.rsplit("#", 1)
                got.setdefault(run, {})[step] = en
                added += 1
    dest.write_text(json.dumps(got, indent=1, ensure_ascii=False))
    log(f"  translated {added} of {len(keys)} lines (the rest were already English)")
    return got
