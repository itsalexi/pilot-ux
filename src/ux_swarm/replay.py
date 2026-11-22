"""Build a self-contained HTML replay from recorded device interactions."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import tempfile
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .config import Study
from .device_mcp import TOOL_NAMES
from .runner import plan_runs


def _inside(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"recorded path escapes its directory: {name}")
    return path


def _metadata(root: Path, filename: str) -> dict:
    path = _inside(root, filename)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _outcome(directory: Path) -> str:
    status = _metadata(directory, "outcome.json").get("status")
    if status == "done":
        verdict = _metadata(directory, "verdict.json").get("verdict")
        return {"verified": "Verified success", "not_verified": "Unverified claim",
                "unclear": "Unclear claim"}.get(verdict, "Claimed success")
    return {"gave_up": "Gave up", "out_of_patience": "Out of patience",
            "abandoned": "Abandoned", "error": "Error"}.get(status, "Incomplete")


class _Images:
    """Index the recorded pixels once across all included sessions."""

    def __init__(self) -> None:
        self.urls: list[str] = []
        self.sizes: list[tuple[int, int]] = []
        self.by_digest: dict[bytes, int] = {}

    def add(self, directory: Path, reference: str | None) -> int | None:
        if not reference:
            return None
        shots = _inside(directory, "shots")
        path = _inside(directory, reference)
        if not path.is_relative_to(shots):
            raise ValueError(f"expected a recorded screenshot in shots/: {reference}")
        if not path.is_file():
            return None
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).digest()
        if digest not in self.by_digest:
            try:
                with Image.open(io.BytesIO(raw)) as source:
                    pixels = source.convert("RGB")
            except (UnidentifiedImageError, OSError):
                return None
            # Export just the pixels, discarding source metadata and ancillary chunks.
            pixels.info.clear()
            encoded = io.BytesIO()
            pixels.save(encoded, format="PNG")
            self.by_digest[digest] = len(self.urls)
            self.urls.append("data:image/png;base64," + base64.b64encode(encoded.getvalue()).decode("ascii"))
            self.sizes.append(pixels.size)
        return self.by_digest[digest]


def _number(value) -> bool:
    return type(value) in (float, int) and math.isfinite(value)


def _steps(directory: Path, images: _Images) -> list[dict]:
    path = _inside(directory, "steps.jsonl")
    if not path.is_file():
        return []
    steps = []
    start = None
    with path.open(encoding="utf-8") as lines:
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                if not line.endswith("\n"):
                    break  # A running device can still be writing its last step.
                raise ValueError(f"{directory.name}/steps.jsonl, line {line_number}: invalid JSON") from error
            index = row.get("i", line_number - 1)
            if type(index) is not int or row.get("tool") not in TOOL_NAMES:
                continue
            before = steps[-1]["image"] if steps and steps[-1]["i"] == index - 1 else None
            shot = images.add(directory, row.get("shot"))
            x = y = None
            if row["tool"] == "tap" and before is not None:
                width, height = images.sizes[before]
                args = row.get("args", {})
                px, py = args.get("x"), args.get("y")
                if _number(px) and _number(py) and 0 <= px < width and 0 <= py < height:
                    x, y = px / width, py / height
            timestamp = row.get("ts")
            if _number(timestamp) and start is None:
                start = timestamp
            elapsed = round(timestamp - start, 3) if _number(timestamp) and timestamp >= start else None
            # device_mcp records the public say argument in the historical "thought" field.
            say = row.get("say", row.get("thought", ""))
            steps.append({"i": index, "tool": row["tool"], "say": say if isinstance(say, str) else "",
                          "image": shot, "before": before, "x": x, "y": y, "time": elapsed})
    return steps


def collect_replay(study: Study, out_dir: Path, session_ids: list[str] | None = None,
                   start_step: int | None = None) -> dict:
    """Collect recorded runs in order. start_step is the first session's recorded step ID."""
    out_dir = Path(out_dir).resolve()
    recorded = _metadata(out_dir, "study.lock.json").get("study")
    if recorded:
        study = Study.model_validate(recorded)
    runs = _inside(out_dir, "runs")
    specs = {spec.id: spec for spec in plan_runs(study)}
    selected = list(dict.fromkeys(session_ids)) if session_ids is not None else list(specs)
    unknown = set(selected).difference(specs)
    if unknown:
        raise ValueError("unknown session IDs: " + ", ".join(sorted(unknown)))
    images = _Images()
    sessions = []
    for run_id in selected:
        directory = _inside(runs, run_id)
        steps = _steps(directory, images)
        if not steps:
            if session_ids is not None:
                raise ValueError(f"no recorded steps for {run_id}")
            continue
        spec = specs[run_id]
        sessions.append({"id": run_id, "persona": spec.persona.name, "task": spec.task.id,
                         "goal": spec.task.goal, "outcome": _outcome(directory), "steps": steps})
    if not sessions and (session_ids is not None or start_step is not None):
        raise ValueError("no recorded device steps to replay")
    data = {"title": study.name, "sessions": sessions, "images": images.urls}
    if start_step is not None:
        first = sessions[0]
        if start_step not in {step["i"] for step in first["steps"]}:
            raise ValueError(f"no recorded step {start_step} in first session {first['id']}")
        data["start"] = {"session": first["id"], "step": start_step}
    return data


def render_replay(data: dict) -> str:
    """Render the shared replay player and its recording into one offline HTML document."""
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=True).replace("<", r"\u003c")
    template = Path(__file__).with_name("replay.html").read_text(encoding="utf-8")
    return template.replace("__UX_REPLAY_DATA__", payload)


def build_replay(study: Study, out_dir: Path, output: Path, session_ids: list[str] | None = None,
                 start_step: int | None = None) -> Path:
    """Write a standalone replay. start_step is the first session's zero-based recorded step ID."""
    data = collect_replay(study, out_dir, session_ids, start_step)
    if not data["sessions"]:
        raise ValueError("no recorded device steps to replay")
    html = render_replay(data)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, delete=False, suffix=".tmp") as temp:
        tmp = Path(temp.name)
    try:
        tmp.write_text(html, encoding="utf-8")
        tmp.replace(output)
    finally:
        tmp.unlink(missing_ok=True)
    return output
