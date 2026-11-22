"""Thin wrapper over `claude -p` with isolation flags."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import env as pilot_env

CLAUDE_BIN = pilot_env("CLAUDE_BIN", "claude")


@dataclass
class ClaudeResult:
    ok: bool
    text: str
    structured: dict | None
    usage: dict = field(default_factory=dict)
    cost_usd: float = 0.0


def build_cmd(model: str, system_prompt: str, user_prompt: str, mcp_config: Path | None,
              tools: str = "", allowed: list[str] | None = None, json_schema: dict | None = None) -> list[str]:
    """Isolated, non-interactive Claude Code invocation: no user settings, CLAUDE.md, hooks or plugins."""
    cmd = [CLAUDE_BIN, "-p", user_prompt,
           "--model", model,
           "--system-prompt", system_prompt,
           "--setting-sources", "",
           "--tools", tools,
           "--strict-mcp-config",
           "--output-format", "stream-json", "--verbose",
           "--no-session-persistence"]
    if os.environ.get("ANTHROPIC_API_KEY"):
        cmd.append("--bare")
    if mcp_config:
        cmd += ["--mcp-config", str(mcp_config)]
    if allowed:
        cmd += ["--allowedTools", ",".join(allowed)]
    if json_schema:
        cmd += ["--json-schema", json.dumps(json_schema)]
    return cmd


async def run(cmd: list[str], cwd: Path, timeout_s: float = 1800, raw_path: Path | None = None) -> ClaudeResult:
    env = dict(os.environ)
    proc = await asyncio.create_subprocess_exec(*cmd, cwd=str(cwd), stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE, env=env, limit=1 << 26)
    result: dict | None = None
    raw = open(raw_path, "w") if raw_path else None

    async def pump():
        nonlocal result
        async for line in proc.stdout:
            if raw:
                raw.write(line.decode(errors="replace"))
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("type") == "result":
                result = d

    try:
        await asyncio.wait_for(pump(), timeout_s)
        await proc.wait()
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return ClaudeResult(False, "timeout", None)
    finally:
        if raw:
            raw.close()
    if not result:
        err = (await proc.stderr.read()).decode(errors="replace")[-800:]
        return ClaudeResult(False, err or f"exit {proc.returncode}", None)
    return ClaudeResult(ok=not result.get("is_error") and proc.returncode == 0,
                        text=result.get("result") or "", structured=result.get("structured_output"),
                        usage=result.get("usage") or {}, cost_usd=result.get("total_cost_usd") or 0.0)


async def ask_json(model: str, system: str, prompt: str, schema: dict, files: dict[str, Path] | None = None,
                   timeout_s: float = 900, retries: int = 2, log_path: Path | None = None) -> dict:
    """One-shot structured call. `files` (name -> source) are copied into a private temp cwd readable via Read."""
    with tempfile.TemporaryDirectory(prefix="pilot-") as d:
        cwd = Path(d)
        for name, src in (files or {}).items():
            dst = cwd / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            if Path(src).is_dir():
                shutil.copytree(src, dst)
            else:
                shutil.copy(src, dst)
        tools = "Read" if files else ""
        cmd = build_cmd(model, system, prompt, None, tools=tools, allowed=["Read"] if files else None,
                        json_schema=schema)
        last = None
        for attempt in range(retries + 1):
            r = await run(cmd, cwd, timeout_s, raw_path=log_path)
            if r.ok and isinstance(r.structured, dict):
                return r.structured
            last = r.text
            await asyncio.sleep(10 * (attempt + 1))
        raise RuntimeError(f"claude structured call failed: {last}")
