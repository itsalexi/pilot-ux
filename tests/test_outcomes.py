import json

import pytest

from ux_swarm import outcomes
from ux_swarm.device_mcp import Session


def test_device_finish_only_completes_when_publication_succeeds(tmp_path, monkeypatch):
    session = Session(None, tmp_path, patience=3)

    def interrupted_replace(source, destination):
        assert json.loads(source.read_text())["status"] == "done"
        assert not destination.exists()
        raise InterruptedError

    with monkeypatch.context() as patch:
        patch.setattr(outcomes.os, "replace", interrupted_replace)
        with pytest.raises(InterruptedError):
            session._finish("done")

    assert not session.over
    assert not list(tmp_path.glob(".outcome-*"))
    session._finish("done")
    assert session.over
    assert json.loads((tmp_path / "outcome.json").read_text()) == {"status": "done", "steps": 0}


def test_interrupted_finalization_preserves_device_outcome(tmp_path, monkeypatch):
    path = tmp_path / "outcome.json"
    original = {"status": "done", "steps": 3, "summary": "Listo."}
    outcomes.write_outcome(tmp_path, original)

    def interrupted_dump(data, handle, **kwargs):
        handle.write('{"status":')
        handle.flush()
        assert json.loads(path.read_text()) == original
        raise InterruptedError

    monkeypatch.setattr(outcomes.json, "dump", interrupted_dump)
    with pytest.raises(InterruptedError):
        outcomes.write_outcome(tmp_path, {**original, "contaminated": False})
    assert json.loads(path.read_text()) == original
    assert not list(tmp_path.glob(".outcome-*"))
