from pilot_ux import env


def test_pilot_env_wins_over_legacy(monkeypatch):
    monkeypatch.setenv("PILOT_CODEX_BIN", "/new/codex")
    monkeypatch.setenv("UX_SWARM_CODEX_BIN", "/old/codex")
    assert env("CODEX_BIN", "codex") == "/new/codex"


def test_legacy_ux_swarm_env_still_works(monkeypatch):
    monkeypatch.delenv("PILOT_STORAGE_STATE", raising=False)
    monkeypatch.setenv("UX_SWARM_STORAGE_STATE", "state.json")
    assert env("STORAGE_STATE") == "state.json"


def test_default_when_unset(monkeypatch):
    monkeypatch.delenv("PILOT_CACHE", raising=False)
    monkeypatch.delenv("UX_SWARM_CACHE", raising=False)
    assert env("CACHE", "fallback") == "fallback"
