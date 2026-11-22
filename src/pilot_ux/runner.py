"""Fan out isolated persona sessions: personas x tasks x runs."""
from __future__ import annotations

import asyncio
import errno
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path

from . import agents, claude, codex
from .config import Persona, Study, Task
from .outcomes import write_outcome
from .prompts import render

BACKOFF = [30, 90]
SESSION_TIMEOUT_S = 45 * 60
FINAL = {"done", "gave_up", "out_of_patience"}
_DRAIN_MARKER = ".pilot-drain"


def request_drain(out: Path) -> None:
    """Hold new participant starts in this output directory until cleared."""
    out.mkdir(parents=True, exist_ok=True)
    (out / _DRAIN_MARKER).touch()


def clear_drain(out: Path) -> None:
    """Allow a subsequent run to collect any remaining sessions."""
    (out / _DRAIN_MARKER).unlink(missing_ok=True)


@dataclass
class RunSpec:
    id: str
    persona: Persona
    task: Task
    n: int


def plan_runs(study: Study) -> list[RunSpec]:
    return [RunSpec(f"{p.id}__{t.id}__r{n}", p, t, n)
            for p in study.personas for t in study.tasks for n in range(1, study.runs + 1)]


def product_hint(study: Study) -> str:
    return study.product_hint or "a new app"


def _claude_version() -> str:
    try:
        return subprocess.run([claude.CLAUDE_BIN, "--version"], capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception:
        return "unknown"


_ROLES = ("persona", "interview", "canary", "verifier", "annotator", "merger", "matcher")


def _model_schedule(study: Study, legacy_pins: dict | None = None) -> dict[str, list[str]]:
    """Resolve active model choices, including per-repeat persona and interview overrides."""
    schedule = {}
    for role in _ROLES:
        repeats = range(1, study.runs + 1) if role in ("persona", "interview") else [None]
        backends = [study.backend_for(role, n) for n in repeats]
        models = {}
        for backend in set(backends):
            if legacy_pins is None:
                model = study.model_for(role, backend)
            else:
                pin = legacy_pins.get(role, "")
                if pin.startswith(f"{backend}:"):
                    model = pin.removeprefix(f"{backend}:")
                elif backend == "claude":
                    # Early Claude-only locks saved unqualified model names.
                    model = pin if pin and ":" not in pin else study.model_for(role, backend)
                else:
                    # Today's machine-wide Codex default is not evidence of an old run's model.
                    model = study.codex_models.get(role) or study.codex_model or ""
            models[backend] = f"{backend}:{model}"
        schedule[role] = [models[b] for b in backends]
    return schedule


def _study_design(study: Study) -> dict:
    # Compare the effective model schedule separately from unused configuration defaults.
    operational = {"concurrency", "out_dir", "root", "model", "models", "backend", "backends",
                   "run_backends", "codex_model", "codex_models"}
    return study.model_dump(mode="json", exclude=operational)


def write_lock(study: Study, out: Path, selected: list[RunSpec] | None = None) -> list[RunSpec]:
    """Verify the existing collection before any resumed session can modify its artifacts."""
    specs = plan_runs(study)
    selected = specs if selected is None else selected
    lock_path = out / "study.lock.json"

    def refuse(reason):
        raise ValueError(f"Cannot resume {out}: {reason}. Use a fresh out_dir for new observations.")

    current = _model_schedule(study)
    if lock_path.exists():
        lock = json.loads(lock_path.read_text())
        if not lock.get("study"):
            refuse("the existing study lock has no recorded configuration")
        recorded = Study.model_validate(lock["study"])
        before, after = _study_design(recorded), _study_design(study)
        changed = [k for k in after if before[k] != after[k]]
        if changed:
            refuse("study settings changed (" + ", ".join(changed) + ")")
        outcomes = {s.id: _read_outcome(out / "runs" / s.id) or {} for s in specs}
        pending = [s for s in selected if outcomes[s.id].get("status") not in FINAL | {"abandoned"}]
        previous = lock.get("model_schedule") or _model_schedule(recorded, lock.get("models", {}))
        for role, values in current.items():
            prior = previous.get(role, [])
            if len(prior) != len(values):
                refuse(f"the {role} model schedule changed")
            for old, new in zip(prior, values):
                if old != new and (pending or not old.endswith(":") or not new.startswith(old)):
                    refuse(f"the {role} backend or model changed or is unrecorded ({old} vs {new})")
        for s in specs:
            outcome = outcomes[s.id]
            backend, model = current["persona"][s.n - 1].split(":", 1)
            if ((outcome.get("backend") and outcome["backend"] != backend)
                    or (outcome.get("model") and outcome["model"] != model)):
                refuse(f"recorded session {s.id} has a different backend or model")
        if "target_build" in lock:
            if lock["target_build"] != target_build(study, out):
                refuse("the target build changed")
        elif pending and target_build(study, out) is not None:
            refuse("this historical lock did not record the target build")
        return pending

    run_root = out / "runs"
    if (run_root.exists() and any(run_root.iterdir())) or any(
        (out / name).exists() for name in ("issues.json", "eval", "report.md", "report.html")
    ):
        refuse("recordings or analysis already exist without a study lock")
    defaults = {}
    for role, choices in current.items():
        default_backend = study.backend_for(role)
        defaults[role] = next((v for v in choices if v.startswith(f"{default_backend}:")), choices[0])
    lock = {"study": study.model_dump(mode="json"), "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "models": defaults, "model_schedule": current, "run_backends": study.run_backends,
            "target_build": target_build(study, out)}
    if any(v.startswith("claude:") for choices in current.values() for v in choices):
        lock["claude_version"] = _claude_version()
    temp = tempfile.NamedTemporaryFile(dir=out, mode="w", encoding="utf-8", delete=False)
    try:
        with temp:
            json.dump(lock, temp, indent=2, ensure_ascii=False)
        os.replace(temp.name, lock_path)
    finally:
        Path(temp.name).unlink(missing_ok=True)
    return selected


_BUILD_MAX_FILES = 10_000
_BUILD_MAX_BYTES = 512 * 1024 * 1024
_BUILD_SKIP_DIRS = {".git", ".hg", ".svn", ".venv", ".pytest_cache", ".mypy_cache", ".ruff_cache",
                    ".gradle", ".turbo", "__pycache__", "node_modules", "DerivedData"}


def target_build(study: Study, out: Path) -> str | None:
    """Identify the local files presented to the device, or use the study's deployment identifier."""
    target = study.target
    if target.build_id:
        return f"id:{target.build_id}"
    if target.kind == "proto" and target.flow:
        flow_path = Path(target.flow).resolve()
        root = flow_path.parent
    elif target.kind == "static" and target.folder:
        root = Path(target.folder).resolve()
    elif target.kind == "ios" and target.ios_app_path:
        root = Path(target.ios_app_path).resolve()
    else:
        return None
    output = out.resolve()
    hint = "Set target.build_id to an identifier for this build."
    if not root.is_dir() or (target.kind != "proto" and root == output):
        raise ValueError(f"Expected a target folder separate from the run output: {root}. {hint}")

    records = {}
    remaining = _BUILD_MAX_BYTES

    def is_results_folder(folder: Path) -> bool:
        return folder == output or (target.kind == "static" and (folder / "study.lock.json").is_file())

    def add_file(path: Path):
        nonlocal remaining
        name = path.relative_to(root).as_posix()
        if name in records:
            return
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise ValueError(f"Cannot resolve target asset {name!r}. {hint}") from error
        if not resolved.is_relative_to(root):
            raise ValueError(f"Target asset {name!r} points outside its folder. {hint}")
        if len(records) >= _BUILD_MAX_FILES:
            raise ValueError(f"Target exceeds the {_BUILD_MAX_FILES:,}-file fingerprint limit. {hint}")
        if path.is_symlink() and target.kind != "proto":
            dest = resolved.relative_to(root)
            ancestors = (p for p in (resolved, *resolved.parents) if root in p.parents)
            if _BUILD_SKIP_DIRS.intersection(dest.parts) or any(is_results_folder(p) for p in ancestors):
                raise ValueError(f"Target asset {name!r} points into an excluded directory. {hint}")
            if resolved.is_dir():
                # Hash the destination's files under their own paths to avoid link cycles.
                records[name] = "dir:" + dest.as_posix()
                return
        if not resolved.is_file():
            raise ValueError(f"Expected a regular target asset at {name!r}. {hint}")
        if resolved.stat().st_size > remaining:
            raise ValueError(f"Target exceeds the {_BUILD_MAX_BYTES:,}-byte fingerprint limit. {hint}")
        digest = hashlib.sha256()
        with resolved.open("rb") as source:
            while chunk := source.read(min(1024 * 1024, remaining + 1)):
                remaining -= len(chunk)
                if remaining < 0:
                    raise ValueError(f"Target exceeds the {_BUILD_MAX_BYTES:,}-byte fingerprint limit. {hint}")
                digest.update(chunk)
        records[name] = digest.hexdigest()

    if target.kind == "proto":
        from .proto import load_flow
        add_file(flow_path)
        for screen in load_flow(flow_path).screens.values():
            image = root / screen.image
            if not image.is_relative_to(root):
                raise ValueError(f"Prototype image {screen.image!r} is outside its folder. {hint}")
            add_file(image)
    else:
        folders = [root]
        dir_count = 1
        while folders:
            with os.scandir(folders.pop()) as entries:
                for entry in entries:
                    asset = Path(entry.path)
                    if asset == output or entry.name == ".DS_Store" or entry.name in _BUILD_SKIP_DIRS:
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if is_results_folder(asset):
                            continue
                        dir_count += 1
                        if dir_count > _BUILD_MAX_FILES:
                            raise ValueError(f"Target exceeds the {_BUILD_MAX_FILES:,}-directory fingerprint limit. {hint}")
                        folders.append(asset)
                    else:
                        add_file(asset)
    manifest = json.dumps([target.kind, records], sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(manifest).hexdigest()


class TargetHost:
    """Starts whatever local server a target needs. Prototype servers are per run so gap logs stay separate."""

    def __init__(self, study: Study):
        self.study = study
        self._stack = ExitStack()
        self._static_url: str | None = None
        self._flow = None

    def __enter__(self):
        t = self.study.target
        if t.kind == "static":
            from .proto import serve_static
            srv = serve_static(t.folder, start=t.url or "index.html", salt=self.study.name)
            self._stack.callback(srv.close)
            self._static_url = srv.url
        elif t.kind == "proto":
            from .proto import load_flow
            self._flow = load_flow(t.flow)
        return self

    def __exit__(self, *exc):
        self._stack.close()

    def url_for(self, run_dir: Path, stack: ExitStack, task: Task | None = None) -> str | None:
        t = self.study.target
        if t.kind == "proto":
            from .proto import serve_proto
            flow = self._flow
            if task and task.start:
                if task.start not in flow.screens:
                    raise ValueError(f"task {task.id}: start screen {task.start!r} not in flow")
                flow = flow.model_copy(update={"start": task.start})
            srv = serve_proto(flow, log_dir=run_dir, salt=self.study.name)
            stack.callback(srv.close)
            return srv.url
        if t.kind == "static":
            return self._static_url
        return t.url


async def run_session(study: Study, spec: RunSpec, run_dir: Path, url: str | None) -> claude.ClaudeResult:
    target_json = run_dir / "target.json"
    target_json.write_text(study.target.model_dump_json())
    mcp = {"mcpServers": {"device": {
        "command": sys.executable,
        "args": ["-m", "pilot_ux.device_mcp", "--run-dir", str(run_dir), "--target-json", str(target_json),
                 "--patience", str(spec.persona.patience_steps)] + (["--url", url] if url else []),
    }}}
    (run_dir / "device.json").write_text(json.dumps(mcp))
    proto_note = ("This is an early prototype. Some screens show sample names and numbers that won't match your "
                  "situation exactly, some things are already filled in, and some buttons don't work yet. Use it as if "
                  "it were real and don't give up just because the sample data differs."
                  if study.target.fidelity == "prototype" else "")
    from .device_mcp import TOOL_NAMES
    device_tools = ", ".join(t for t in TOOL_NAMES if t != "reopen" or study.target.kind != "ios")
    system = render("persona", card=spec.persona.card(), product_hint=product_hint(study), device_tools=device_tools,
                    patience=spec.persona.patience_steps) + ("\n" + proto_note if proto_note else "")
    user = render("persona_task", context=spec.task.context or "", goal=spec.task.goal)
    backend = study.backend_for("persona", spec.n)
    if backend == "codex":
        with tempfile.TemporaryDirectory(prefix="pilot-") as cwd:
            cmd = codex.build_cmd(study.model_for("persona", "codex"), system + "\n\n---\n\n" + user, Path(cwd),
                                  mcp=mcp["mcpServers"]["device"])
            return await codex.run(cmd, SESSION_TIMEOUT_S, raw_path=run_dir / "agent.jsonl")
    cmd = claude.build_cmd(study.model_for("persona"), system, user, run_dir / "device.json",
                           allowed=["mcp__device"])
    with tempfile.TemporaryDirectory(prefix="pilot-") as cwd:  # empty: nothing to read, nothing to leak
        res = await claude.run(cmd, Path(cwd), SESSION_TIMEOUT_S, raw_path=run_dir / "agent.jsonl")
    if device_failed(run_dir / "agent.jsonl"):
        return claude.ClaudeResult(False, f"device MCP server failed to start; see {run_dir / 'device.log'}", None)
    return res


def device_failed(agent_log: Path) -> bool:
    try:
        init = json.loads(agent_log.read_text().splitlines()[0])
    except (OSError, IndexError, ValueError):
        return False
    return any(s.get("name") == "device" and s.get("status") != "connected" for s in init.get("mcp_servers", []))


CANARY_SCHEMA = {"type": "object", "properties": {"prior_knowledge": {"type": "boolean"}, "why": {"type": "string"}},
                 "required": ["prior_knowledge", "why"]}


async def check_canary(study: Study, run_dir: Path) -> bool:
    steps = run_dir / "steps.jsonl"
    if not steps.is_file():
        raise ValueError("Cannot assess prior knowledge without a first observation")
    with steps.open(encoding="utf-8") as stream:
        first = json.loads(stream.readline().strip() or "{}")
    answer = first.get("say", first.get("thought")) if isinstance(first, dict) else None
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("Cannot assess prior knowledge without a first spoken comment")
    r = await agents.ask_json(study, "canary", "You are a careful research assistant.",
                              render("canary", product_hint=product_hint(study), answer=answer),
                              CANARY_SCHEMA)
    prior = r.get("prior_knowledge") if isinstance(r, dict) else None
    if type(prior) is not bool:
        raise ValueError("Canary response needs a boolean prior_knowledge assessment")
    return prior


def _read_outcome(run_dir: Path) -> dict | None:
    p = run_dir / "outcome.json"
    return json.loads(p.read_text()) if p.exists() else None


async def _one(study: Study, spec: RunSpec, out: Path, host: TargetHost, sem: asyncio.Semaphore, log) -> bool:
    run_dir = out / "runs" / spec.id
    prev = _read_outcome(run_dir)
    if prev and prev.get("status") in FINAL | {"abandoned"}:
        return True
    async with sem:
        # Check admission after obtaining a slot, before touching partial recordings.
        if (out / _DRAIN_MARKER).exists():
            return False
        for attempt in range(len(BACKOFF) + 1):
            if run_dir.exists():
                shutil.rmtree(run_dir)
            run_dir.mkdir(parents=True)
            t0 = time.time()
            with ExitStack() as stack:
                url = host.url_for(run_dir, stack, spec.task)
                res = await run_session(study, spec, run_dir, url)
            outcome = _read_outcome(run_dir)
            if outcome and (outcome["status"] in FINAL or (outcome["status"] == "abandoned" and res.ok)):
                break
            log(f"  {spec.id}: attempt {attempt + 1} failed ({res.text[:120]!r})")
            if attempt < len(BACKOFF):
                await asyncio.sleep(BACKOFF[attempt])
        outcome = _read_outcome(run_dir) or {"status": "error", "error": res.text[:500], "steps": 0}
        be = study.backend_for("persona", spec.n)
        outcome.update(seconds=round(time.time() - t0), cost_usd=res.cost_usd, backend=be,
                       model=study.model_for("persona", be),
                       persona=spec.persona.id, task=spec.task.id, run=spec.n)
        try:
            outcome["contaminated"] = await check_canary(study, run_dir)
        except Exception as e:  # canary is a guard, not a blocker
            outcome["contaminated"] = None
            outcome["canary_error"] = str(e)[:200]
        write_outcome(run_dir, outcome)
        log(f"  {spec.id}: {outcome['status']} in {outcome.get('steps', 0)} steps")
        return True


@contextmanager
def _exclusive_output(out: Path):
    with ExitStack() as stack:
        try:
            if os.name == "nt":
                import msvcrt
                handle = stack.enter_context((out / ".pilot.lock").open("a+b"))
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                descriptor = os.open(out, os.O_RDONLY)
                stack.callback(os.close, descriptor)
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            if e.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise
            raise ValueError(f"Another runner is already using {out}") from e
        yield


async def run_study(study: Study, out: Path, only: list[str] | None = None, log=print) -> bool:
    """Collect selected sessions. Return False when a drain leaves any unstarted."""
    specs = [s for s in plan_runs(study) if not only or any(o in s.id for o in only)]
    if not specs:
        return True
    out.mkdir(parents=True, exist_ok=True)
    with _exclusive_output(out):
        pending = write_lock(study, out, specs)
        if not pending:
            return True
        if (out / _DRAIN_MARKER).exists():
            return False
        sem = asyncio.Semaphore(study.persona_concurrency)
        with TargetHost(study) as host:
            results = await asyncio.gather(*(_one(study, s, out, host, sem, log) for s in pending),
                                           return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                raise result
        return all(results)
