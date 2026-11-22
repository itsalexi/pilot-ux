import shutil

from ux_swarm import config
from ux_swarm.cli import main


def study_file(tmp_path, extra=""):
    path = tmp_path / "study.yaml"
    path.write_text(
        "name: demo\ntarget: {kind: url, url: 'http://localhost'}\n"
        "tasks: [{id: add, goal: add one, success_criteria: [visible]}]\n"
        "personas: [{ref: default/older-non-techy}]\nruns: 3\n"
        "backend: codex\nmodel: claude-fallback\ncodex_model: codex-fallback\n"
        "models: {persona: claude-persona}\ncodex_models: {persona: codex-persona}\n" + extra
    )
    return str(path)


def test_all_dry_run_names_codex_persona_model(tmp_path, capsys):
    main(["all", study_file(tmp_path), "--dry-run"])
    text = capsys.readouterr().out
    assert "3 persona sessions" in text
    assert "codex:codex-persona" in text
    assert "claude" not in text and "fallback" not in text


def test_held_all_exits_before_analysis(tmp_path, monkeypatch, capsys):
    from ux_swarm import cli

    path = study_file(tmp_path)
    out = str(tmp_path / "runs")
    main(["drain", out])

    def unexpected(_):
        raise AssertionError("a held study advanced to a downstream stage")

    for name in ("cmd_interview", "cmd_analyze", "cmd_report"):
        monkeypatch.setattr(cli, name, unexpected)
    main(["all", path])
    assert "on hold with unstarted sessions" in capsys.readouterr().out
    main(["drain", out, "--clear"])
    assert "Hold cleared" in capsys.readouterr().out


def test_mixed_dry_run_follows_selected_run_numbers(tmp_path, capsys):
    path = study_file(tmp_path, "run_backends: [claude, codex]\n")
    main(["run", path, "--dry-run"])
    text = capsys.readouterr().out
    assert text.count("claude:claude-persona") == 1
    assert text.count("codex:codex-persona") == 1

    main(["run", path, "--dry-run", "--only", "__r2"])
    text = capsys.readouterr().out
    assert "1 persona session (selected from 3 planned)" in text
    assert "5-6 estimated model calls" in text
    assert "codex:codex-persona" in text and "claude" not in text

    main(["run", path, "--dry-run", "--only", "does-not-exist"])
    assert "0 persona sessions selected" in capsys.readouterr().out


def test_init_then_dry_run_from_installed_layout(tmp_path, monkeypatch, capsys):
    package = tmp_path / "site-packages" / "ux_swarm"
    for name in ("templates", "personas"):
        shutil.copytree(config.data_dir(name), package / "_data" / name)
    monkeypatch.setattr(config, "__file__", str(package / "config.py"))

    destination = tmp_path / "my-study"
    main(["init", str(destination)])
    main(["run", str(destination / "study.yaml"), "--dry-run"])

    assert (destination / "persona.yaml").is_file()
    assert "9 persona sessions" in capsys.readouterr().out
