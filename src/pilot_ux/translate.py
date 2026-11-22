"""English line for every think-aloud step that wasn't said in English, cached in translations.json."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
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
_EN = set("""i you he she we they it me my your our their this that these those the a an and or but if so of in on at to for
from with about as is are was were be been am do does did don't doesn't can can't cannot will won't would should could
i'm i'll i've i'd it's that's there's what's let's not no yes here there where what when why how which who just now
then back see look looks seems tap open go get got need want try trying still maybe okay ok think know""".split())


def looks_english(line: str) -> bool:
    """Cheap filter so all-English studies send nothing to translate: a line counts as English when at least a
    fifth of its words are common English function words. Very short lines are left alone."""
    words = re.findall(r"[a-z']+", line.lower().replace("’", "'"))
    if len(words) <= 2:
        return True
    return sum(w in _EN for w in words) / len(words) >= 0.2


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


def _reasons(out: Path) -> dict[str, str]:
    """Why each session ended, in the tester's words: the report shows it as the session's last caption."""
    reasons = {}
    for rd in sorted((out / "runs").glob("*__*__r*")):
        p = rd / "outcome.json"
        reason = (json.loads(p.read_text()).get("reason") or "") if p.exists() else ""
        if reason.strip():
            reasons[f"r#{rd.name}"] = reason
    return reasons


async def translate(study: Study, out: Path, log=print) -> dict[str, dict[str, str]]:
    dest = out / "translations.json"
    got: dict[str, dict[str, str]] = json.loads(dest.read_text()) if dest.exists() else {}
    lines: dict[str, str] = {}
    if not dest.exists():
        lines.update(_lines(out))
    if "_quotes" not in got:
        lines.update(_quotes(out))
    if "_reasons" not in got:
        lines.update(_reasons(out))
    lines = {k: v for k, v in lines.items() if not looks_english(v)}
    if not lines:
        got.setdefault("_quotes", {})
        got.setdefault("_reasons", {})
        dest.write_text(json.dumps(got, indent=1, ensure_ascii=False))
        return got
    keys = list(lines)
    sem = asyncio.Semaphore(max(1, study.concurrency))

    async def batch(ks: list[str]) -> list[dict]:
        body = "\n".join(json.dumps({"k": k, "line": lines[k]}, ensure_ascii=False) for k in ks)
        async with sem:
            res = await agents.ask_json(study, "translator", SYSTEM, PROMPT.format(lines=body), SCHEMA)
        return res.get("lines", [])

    got.setdefault("_quotes", {})
    got.setdefault("_reasons", {})
    added = 0
    for part in await asyncio.gather(*(batch(keys[i:i + BATCH]) for i in range(0, len(keys), BATCH))):
        for row in part:
            en = (row.get("en") or "").strip()
            k = row.get("k", "")
            if en and k in lines and en != lines[k].strip():
                run, step = (("_quotes", k[2:]) if k.startswith("q#") else ("_reasons", k[2:]) if k.startswith("r#")
                             else k.rsplit("#", 1))
                got.setdefault(run, {})[step] = en
                added += 1
    dest.write_text(json.dumps(got, indent=1, ensure_ascii=False))
    log(f"  translated {added} of {len(keys)} lines (the rest were already English)")
    return got
