"""OpenAI Codex CLI backend (`codex exec`), locked down to the device MCP server.

Isolation: a throwaway CODEX_HOME holding only a symlink to the user's auth.json (so no global AGENTS.md,
memories, skills, plugins or MCP servers), --ignore-rules, an empty cwd, read-only sandbox, and every
built-in capability that could see the disk or the web disabled.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import shutil
import tempfile
from pathlib import Path

from . import env as pilot_env
from .claude import ClaudeResult

CODEX_BIN = pilot_env("CODEX_BIN", "codex")
DISABLE = ["shell_tool", "unified_exec", "view_image", "browser_use", "browser_use_external", "in_app_browser",
           "computer_use", "apps", "plugins", "multi_agent", "memories", "image_generation", "skill_search"]


def build_cmd(model: str, prompt: str, cwd: Path, mcp: dict | None = None, schema_path: Path | None = None,
              last_path: Path | None = None, images: list[Path] | None = None) -> list[str]:
    cmd = [CODEX_BIN, "exec", "--json", "--ignore-rules", "--ephemeral", "--skip-git-repo-check",
           "-s", "read-only", "-C", str(cwd), "-m", model,
           "-c", 'approval_policy="never"', "-c", 'web_search="disabled"']
    for f in DISABLE:
        cmd += ["--disable", f]
    if mcp:
        cmd += ["-c", f"mcp_servers.device.command={json.dumps(mcp['command'])}",
                "-c", f"mcp_servers.device.args={json.dumps(mcp['args'])}",
                "-c", 'mcp_servers.device.default_tools_approval_mode="approve"']
    else:
        cmd += ["--disable", "code_mode_host"]
    if schema_path:
        cmd += ["--output-schema", str(schema_path)]
    if last_path:
        cmd += ["-o", str(last_path)]
    for img in images or []:
        cmd += ["-i", str(img)]
    if images:
        cmd.append("--")
    cmd.append(prompt)
    return cmd


def strict(schema: dict) -> dict:
    """OpenAI structured outputs: every object closed and every property required."""
    s = copy.deepcopy(schema)

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(s)
    return s


def parse_events(lines, returncode: int) -> ClaudeResult:
    text, usage, err = "", {}, ""
    for line in lines:
        try:
            d = json.loads(line)
        except ValueError:
            continue
        t = d.get("type")
        if t == "item.completed" and d.get("item", {}).get("type") == "agent_message":
            text = d["item"].get("text", "")
        elif t == "turn.completed":
            usage = d.get("usage", {})
            err = ""
        elif t in ("turn.failed", "error"):
            err = json.dumps(d)[:500]
    ok = returncode == 0 and not err
    return ClaudeResult(ok=ok, text=text if ok else err, structured=None, usage=usage, cost_usd=0.0)


def _home() -> tempfile.TemporaryDirectory:
    src = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "auth.json"
    h = tempfile.TemporaryDirectory(prefix="pilot-codex-")
    if src.exists():
        os.symlink(src, Path(h.name) / "auth.json")
    return h


async def run(cmd: list[str], timeout_s: float = 1800, raw_path: Path | None = None) -> ClaudeResult:
    with _home() as home:
        env = {**os.environ, "CODEX_HOME": home}
        proc = await asyncio.create_subprocess_exec(*cmd, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.PIPE, env=env, limit=1 << 26)
        lines: list[str] = []

        async def pump():
            async for line in proc.stdout:
                lines.append(line.decode(errors="replace"))
        try:
            await asyncio.wait_for(pump(), timeout_s)
            await proc.wait()
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return ClaudeResult(False, "timeout", None)
        if raw_path:
            Path(raw_path).write_text("".join(lines))
        r = parse_events(lines, proc.returncode)
        if not r.ok and not r.text:
            r.text = (await proc.stderr.read()).decode(errors="replace")[-800:] or f"exit {proc.returncode}"
        return r


async def ask_json(model: str, system: str, prompt: str, schema: dict, files: dict[str, Path] | None = None,
                   timeout_s: float = 900, retries: int = 2, log_path: Path | None = None) -> dict:
    """Text files are inlined into the prompt; images (also inside folders) are attached in name order."""
    images, texts = [], []
    for name, src in sorted((files or {}).items()):
        src = Path(src)
        paths = sorted(src.rglob("*")) if src.is_dir() else [src]
        for p in paths:
            rel = f"{name}/{p.relative_to(src)}" if src.is_dir() else name
            if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                images.append((rel, p))
            elif p.is_file():
                texts.append(f"===== {rel} =====\n{p.read_text(errors='replace')}")
    full = system + "\n\n" + prompt
    if texts:
        full += "\n\nThe files mentioned above, inlined:\n\n" + "\n\n".join(texts)
    if images:
        full += ("\n\nImages are attached in this order (the Read tool is not available; use the attachments): "
                 + ", ".join(r for r, _ in images))
    with tempfile.TemporaryDirectory(prefix="pilot-") as d:
        cwd = Path(d)
        sp, lp = cwd / "schema.json", cwd / "last.txt"
        sp.write_text(json.dumps(strict(schema)))
        cmd = build_cmd(model, full, cwd, schema_path=sp, last_path=lp, images=[p for _, p in images])
        last = None
        for attempt in range(retries + 1):
            lp.unlink(missing_ok=True)
            r = await run(cmd, timeout_s, raw_path=log_path)
            last = r.text
            if r.ok:
                try:
                    value = json.loads(lp.read_text() if lp.exists() else r.text)
                except json.JSONDecodeError as e:
                    last = f"invalid JSON in final response: {e}"
                else:
                    if isinstance(value, dict):
                        return value
                    last = "expected a JSON object in the final response"
            if attempt < retries:
                await asyncio.sleep(10 * (attempt + 1))
        raise RuntimeError(f"codex structured call failed: {last}")
