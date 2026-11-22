"""Publish study JSON files without exposing partial results to a resumed run."""

import json
import os
import tempfile
from pathlib import Path


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.stem}-", mode="w",
                                       encoding="utf-8", delete=False)
    temporary_path = Path(temp.name)
    try:
        with temp:
            json.dump(data, temp, ensure_ascii=False, indent=2, allow_nan=False)
            temp.write("\n")
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def write_outcome(run_dir: Path, outcome: dict) -> None:
    write_json(run_dir / "outcome.json", outcome)
