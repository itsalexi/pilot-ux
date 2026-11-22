import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from pilot_ux import codex
from pilot_ux.config import Study, Target, Task


def test_codex_cmd_is_locked_down(tmp_path):
    cmd = codex.build_cmd("gpt-x", "PROMPT", cwd=tmp_path,
                          mcp={"command": "/py", "args": ["-m", "pilot_ux.device_mcp", "--url", "http://x"]})
    j = " ".join(cmd)
    assert cmd[:2] == ["codex", "exec"] and cmd[-1] == "PROMPT"
    assert cmd[cmd.index("-m") + 1] == "gpt-x"
    for flag in ("--ignore-rules", "--ephemeral", "--skip-git-repo-check", "--json"):
        assert flag in cmd
    for feat in ("shell_tool", "unified_exec", "view_image", "browser_use", "computer_use", "multi_agent", "memories"):
        assert f"--disable {feat}" in j
    assert 'mcp_servers.device.default_tools_approval_mode="approve"' in j
    assert 'mcp_servers.device.args=["-m", "pilot_ux.device_mcp", "--url", "http://x"]' in j


def test_strict_schema_closes_objects():
    s = codex.strict({"type": "object", "properties": {"a": {"type": "object", "properties": {"b": {"type": "string"}}}},
                      "required": []})
    assert s["additionalProperties"] is False and s["required"] == ["a"]
    assert s["properties"]["a"]["additionalProperties"] is False and s["properties"]["a"]["required"] == ["b"]


def test_backend_for_role_and_run():
    s = Study(name="s", target=Target(kind="url", url="http://x"), personas=[],
              tasks=[Task(id="t", goal="g", success_criteria=["c"])],
              backend="claude", backends={"annotator": "codex"}, run_backends=["claude", "codex"],
              codex_model="gpt-x")
    assert s.backend_for("annotator") == "codex"
    assert s.backend_for("persona", run=1) == "claude"
    assert s.backend_for("persona", run=2) == "codex"
    assert s.backend_for("persona", run=3) == "claude"  # cycles
    assert s.model_for("persona", backend="codex") == "gpt-x"
    assert s.model_for("persona", backend="claude") == "claude-opus-5-5"


def test_parse_codex_events():
    lines = [json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "hi"}}),
             json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 2}})]
    r = codex.parse_events(lines, returncode=0)
    assert r.ok and r.text == "hi" and r.usage["input_tokens"] == 10


def test_failed_turn_reports_error_after_partial_agent_message():
    lines = [json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "starting"}}),
             json.dumps({"type": "turn.failed", "error": {"message": "request rejected"}})]
    result = codex.parse_events(lines, returncode=1)
    assert not result.ok and "request rejected" in result.text


def test_completed_turn_recovers_from_intermediate_error():
    lines = [json.dumps({"type": "error", "message": "Reconnecting..."}),
             json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "answer"}}),
             json.dumps({"type": "turn.completed"})]
    result = codex.parse_events(lines, returncode=0)
    assert result.ok and result.text == "answer"


async def test_ask_json_rejects_failed_turn_json(monkeypatch):
    failure = '{"type":"turn.failed","error":{"message":"schema rejected"}}'
    monkeypatch.setattr(codex, "run", AsyncMock(return_value=codex.ClaudeResult(False, failure, None)))
    with pytest.raises(RuntimeError, match="schema rejected"):
        await codex.ask_json("model", "system", "prompt", {"type": "object"}, retries=0)


async def test_ask_json_retry_uses_only_current_attempt_output(monkeypatch):
    async def run(cmd, timeout_s, raw_path):
        last_message = Path(cmd[cmd.index("-o") + 1])
        if mock_run.await_count == 1:
            last_message.write_text('{"answer": "incomplete"}')
            return codex.ClaudeResult(False, "interrupted", None)
        return codex.ClaudeResult(True, '{"answer": "complete"}', None)

    mock_run = AsyncMock(side_effect=run)
    monkeypatch.setattr(codex, "run", mock_run)
    monkeypatch.setattr(codex.asyncio, "sleep", AsyncMock())
    result = await codex.ask_json("model", "system", "prompt", {"type": "object"}, retries=1)
    assert result == {"answer": "complete"}
