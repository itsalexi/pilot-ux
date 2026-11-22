"""Prompt templates (string.Template, $name placeholders)."""
from __future__ import annotations

import string
from functools import cache
from pathlib import Path

NAMES = ["persona", "persona_task", "interview", "verifier", "annotator", "merger", "matcher", "canary"]


@cache
def _load(name: str) -> str:
    return (Path(__file__).parent / f"{name}.md").read_text()


def render(name: str, **vars) -> str:
    return string.Template(_load(name)).substitute(**{k: str(v) for k, v in vars.items()})
