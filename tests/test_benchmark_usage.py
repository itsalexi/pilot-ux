import json

import pytest

from pilot_ux.benchmark_usage import summarize_usage


def fixture(root, ids):
    specs = [{"run_id": name, "arm": arm, "task": "water", "panel": 1, "slot": index, "singleton": index == 0}
             for index, (name, arm) in enumerate(ids)]
    (root / "benchmark.json").write_text(json.dumps({"sessions": specs}))
    dirs = []
    for item in specs:
        folder = root / "study" / "runs" / item["run_id"]
        folder.mkdir(parents=True)
        dirs.append(folder)
    return dirs


def logs(folder, outcome, events, actions):
    (folder / "outcome.json").write_text(json.dumps(outcome))
    (folder / "agent.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    (folder / "steps.jsonl").write_text("".join(json.dumps({"i": i, "tool": action}) + "\n"
                                                for i, action in enumerate(actions)))


def test_usage_counts_participant_steps_tokens_and_arm_coverage(tmp_path):
    codex, missing, claude = fixture(tmp_path, [("one", "generic"), ("two", "generic"), ("three", "persona")])
    logs(codex, {"backend": "codex", "steps": 5, "status": "done", "seconds": 8, "cost_usd": 0},
         [{"type": "turn.completed", "usage": {"input_tokens": 100, "cached_input_tokens": 65, "output_tokens": 0}}],
         ["look", "tap", "type_text", "back", "done"])
    logs(claude, {"backend": "claude", "steps": 2, "status": "gave_up", "seconds": 0, "cost_usd": 0},
         [{"type": "result", "total_cost_usd": 0, "usage": {"input_tokens": 17}}], ["look", "give_up"])
    result = summarize_usage(tmp_path)
    one, two, three = result["sessions"]
    assert one["singleton"] is True and one["device_calls"] == 5 and one["ui_actions"] == 3
    assert one["codex_input_tokens"] == 100 and one["codex_cached_input_tokens"] == 65
    assert one["codex_output_tokens"] == 0 and one["provider_cost_usd"] is None
    assert two["device_calls"] is None and three["codex_input_tokens"] is None
    generic, persona = result["arms"]["generic"], result["arms"]["persona"]
    assert generic["planned_sessions"] == 2 and generic["device_calls"] is None
    assert generic["codex_input_tokens"] is None and generic["measured_sessions"]["codex_input_tokens"] == 1
    assert persona["elapsed_seconds"] == persona["provider_cost_usd"] == persona["ui_actions"] == 0
    assert persona["measured_sessions"]["provider_cost_usd"] == 1 and result["study_cost_usd"] is None


@pytest.mark.parametrize("tail", ['{"type":"turn.started"}\n', '{"type":"error"}\n', '{"partially written"'])
def test_damaged_session_does_not_expose_complete_totals(tmp_path, tail):
    folder, = fixture(tmp_path, [("one", "generic")])
    logs(folder, {"backend": "codex", "status": "error", "steps": 5, "seconds": True},
         [{"type": "turn.completed", "usage": {"input_tokens": 100}}], ["look"])
    with (folder / "agent.jsonl").open("a") as f:
        f.write(tail)
    row, = summarize_usage(tmp_path)["sessions"]
    assert all(row[k] is None for k in ("device_calls", "ui_actions", "elapsed_seconds", "codex_input_tokens"))


def test_invalid_counters_and_claude_implicit_zero_stay_unknown(tmp_path):
    codex, claude, billed = fixture(tmp_path, [("one", "generic"), ("two", "persona"), ("three", "persona")])
    logs(codex, {"backend": "codex", "status": "done", "steps": False},
         [{"type": "turn.completed", "usage": {"input_tokens": False, "cached_input_tokens": -1, "output_tokens": 0}}], [])
    logs(claude, {"backend": "claude", "status": "done", "steps": 0, "cost_usd": 0}, [{"type": "result"}], [])
    logs(billed, {"backend": "claude", "status": "done", "cost_usd": 0.21}, [], [])
    one, two, three = summarize_usage(tmp_path)["sessions"]
    assert one["device_calls"] is None and one["codex_input_tokens"] is None
    assert one["codex_cached_input_tokens"] is None and one["codex_output_tokens"] == 0
    assert two["device_calls"] == two["ui_actions"] == 0 and two["provider_cost_usd"] is None
    assert three["provider_cost_usd"] == 0.21
