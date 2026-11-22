"""Backend dispatch: the same roles run on Claude Code (`claude -p`) or OpenAI Codex (`codex exec`)."""
from __future__ import annotations

from pathlib import Path

from . import claude, codex
from .config import Study


async def ask_json(study: Study, role: str, system: str, prompt: str, schema: dict,
                   files: dict[str, Path] | None = None, run: int | None = None) -> dict:
    backend = study.backend_for(role, run)
    model = study.model_for(role, backend)
    mod = codex if backend == "codex" else claude
    return await mod.ask_json(model, system, prompt, schema, files=files)
