"""Study configuration: target, tasks, personas, models."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_serializer, model_validator

DEFAULT_MODEL = "claude-opus-5-5"


REPO_PATHS = {"templates": "skills/ux-swarm/templates", "claude-design": "skills/ux-swarm/claude-design"}


def data_dir(name: str) -> Path:
    """Bundled data folder (personas, anchors, templates, claude-design): repo checkout first, then installed wheel."""
    repo = Path(__file__).resolve().parents[2] / REPO_PATHS.get(name, name)
    if repo.is_dir():
        return repo
    return Path(__file__).resolve().parent / "_data" / name


class Persona(BaseModel):
    id: str
    name: str
    age: int
    locale: str
    device: str
    tech_literacy: int = Field(ge=1, le=5)
    patience_steps: int = Field(ge=3, le=200)
    language_register: str
    goals: list[str]
    fears: list[str]
    habits: list[str]
    notes: str = ""

    def card(self) -> str:
        lines = [
            f"Name: {self.name}, {self.age}",
            f"Where/language: {self.locale}; you talk like this: {self.language_register}",
            f"Phone/device: {self.device}",
            f"Comfort with apps (1-5): {self.tech_literacy}",
            "What you want: " + "; ".join(self.goals),
            "What worries you: " + "; ".join(self.fears),
            "Habits: " + "; ".join(self.habits),
        ]
        if self.notes:
            lines.append(self.notes)
        return "\n".join(lines)


class Task(BaseModel):
    id: str
    goal: str
    success_criteria: list[str]
    start: str | None = None  # optional start screen id / path (setup-side only)
    context: str = ""  # situation in the persona's world, e.g. "you're at dinner with 5 friends"
    verify_after: Literal["reopen"] | None = None

    @model_serializer(mode="wrap")
    def _serialize(self, handler):
        data = handler(self)
        # Existing frozen studies predate this optional verification rule.
        if self.verify_after is None:
            data.pop("verify_after", None)
        return data


class Target(BaseModel):
    kind: Literal["url", "proto", "static", "ios"]
    build_id: str | None = Field(default=None, min_length=1, pattern=r"\S")
    url: str | None = None
    flow: str | None = None
    folder: str | None = None
    app_bundle: str | None = None
    ios_app_path: str | None = None  # simulator .app to reinstall before each attempt
    launch_args: list[str] = Field(default_factory=list)
    udid: str | None = None
    viewport: tuple[int, int] = (390, 844)
    scale: int = 2
    mobile: bool = True
    fidelity: Literal["live", "prototype", "sketch"] = "live"


class Study(BaseModel):
    name: str
    target: Target
    tasks: list[Task]
    personas: list[Persona]
    runs: int = 3
    model: str = DEFAULT_MODEL
    models: dict[str, str] = {}
    embedder: str = "openai:text-embedding-3-small"
    concurrency: int = 4
    out_dir: str = "runs"
    product_hint: str = ""  # one neutral line shown to personas, e.g. "an app for splitting bills"
    root: str = "."
    backend: Literal["claude", "codex"] = "claude"
    backends: dict[str, Literal["claude", "codex"]] = {}  # per role: persona, interview, verifier, annotator, merger, canary, matcher
    run_backends: list[Literal["claude", "codex"]] | None = None  # persona backend per run number, cycled
    codex_model: str | None = None  # pinned Codex model; defaults to `model` in ~/.codex/config.toml
    codex_models: dict[str, str] = {}

    @model_validator(mode="after")
    def _validate_verification_target(self):
        if self.target.kind == "ios" and any(task.verify_after == "reopen" for task in self.tasks):
            raise ValueError("verify_after: reopen requires a web target with a reopen action")
        return self

    @property
    def persona_concurrency(self) -> int:
        # A study targets one simulator; overlapping personas would operate the same screen.
        return 1 if self.target.kind == "ios" else self.concurrency

    def backend_for(self, role: str, run: int | None = None) -> str:
        if role in ("persona", "interview") and run and self.run_backends:
            return self.run_backends[(run - 1) % len(self.run_backends)]
        return self.backends.get(role, self.backend)

    def model_for(self, role: str, backend: str = "claude") -> str:
        if backend == "codex":
            return self.codex_models.get(role) or self.codex_model or default_codex_model()
        return self.models.get(role, self.model)


def default_codex_model() -> str:
    import os
    import tomllib
    cfg = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "config.toml"
    try:
        return tomllib.loads(cfg.read_text())["model"]
    except (OSError, KeyError, ValueError):
        raise ValueError("set codex_model in study.yaml (no default model found in ~/.codex/config.toml)")


def load_persona_ref(ref: str) -> Persona:
    lib, _, pid = ref.partition("/")
    if lib != "default" or not pid:
        raise ValueError(f"unknown persona ref {ref!r}; use default/<id> or an inline persona")
    path = data_dir("personas") / f"{pid}.yaml"
    if not path.exists():
        known = sorted(p.stem for p in data_dir("personas").glob("*.yaml"))
        raise ValueError(f"no default persona {pid!r}; known: {', '.join(known)}")
    return Persona(**yaml.safe_load(path.read_text()))


def load_study(path: str | Path) -> Study:
    path = Path(path).resolve()
    raw = yaml.safe_load(path.read_text())
    base = path.parent
    personas = []
    for entry in raw.get("personas", []):
        if "ref" in entry:
            personas.append(load_persona_ref(entry["ref"]))
        elif "file" in entry:
            personas.append(Persona(**yaml.safe_load((base / entry["file"]).read_text())))
        else:
            personas.append(Persona(**entry))
    raw["personas"] = personas
    tgt = raw.get("target", {})
    for key in ("flow", "folder", "ios_app_path"):
        if tgt.get(key) and not Path(tgt[key]).is_absolute():
            tgt[key] = str(base / tgt[key])
    out = raw.get("out_dir", "runs")
    if not Path(out).is_absolute():
        raw["out_dir"] = str(base / out)
    raw["root"] = str(base)
    return Study(**raw)
