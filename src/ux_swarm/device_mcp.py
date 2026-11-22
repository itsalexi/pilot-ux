"""MCP stdio server giving a persona agent eyes (screenshots) and hands (tap/type/scroll/back) only.

Run: python -m ux_swarm.device_mcp --run-dir DIR --target-json FILE --patience N [--url URL]
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .config import Target
from .outcomes import write_outcome

TOOL_NAMES = ["look", "tap", "type_text", "scroll", "back", "reopen", "give_up", "done"]
OVER = "The session is over. Stop calling tools and write one last sentence in character."


class Session:
    """Pure step/patience/logging logic around a Device; MCP wiring lives below."""

    def __init__(self, device, run_dir: Path, patience: int):
        self.device = device
        self.run_dir = Path(run_dir)
        (self.run_dir / "shots").mkdir(parents=True, exist_ok=True)
        self.patience_max = self.patience = patience
        self.i = 0
        self.last: bytes | None = None
        self.over = False
        self.started = False

    def _finish(self, status: str, **extra) -> None:
        out = {"status": status, **extra, "steps": self.i}
        write_outcome(self.run_dir, out)
        self.over = True

    async def act(self, tool: str, args: dict, thought: str) -> tuple[bytes | None, str]:
        if self.over:
            return None, OVER
        if not self.started:
            await self.device.start()
            self.started = True
        if tool == "tap":
            await self.device.tap(int(args["x"]), int(args["y"]))
        elif tool == "type_text":
            await self.device.type_text(str(args["text"]))
        elif tool == "scroll":
            await self.device.scroll(args.get("direction", "down"), int(args.get("amount", 400)))
        elif tool == "back":
            await self.device.back()
        elif tool == "reopen":
            await self.device.reopen()
        elif tool not in ("look", "give_up", "done"):
            raise ValueError(f"unknown tool {tool}")
        shot = await self.device.screenshot()
        changed = shot != self.last
        if tool != "look" or self.i > 0:
            self.patience -= 1 if changed or tool in ("give_up", "done") else 2
        self.last = shot
        rel = f"shots/{self.i:04d}.png"
        (self.run_dir / rel).write_bytes(shot)
        rec = {"i": self.i, "ts": time.time(), "tool": tool, "args": args, "thought": thought,
               "shot": rel, "changed": changed, "patience_left": max(self.patience, 0)}
        with open(self.run_dir / "steps.jsonl", "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.i += 1
        if tool == "give_up":
            self._finish("gave_up", reason=args.get("reason", ""))
            return shot, OVER
        if tool == "done":
            self._finish("done", summary=args.get("summary", ""))
            return shot, OVER
        if self.patience <= 0:
            self._finish("out_of_patience")
            return shot, "You've run out of patience and close the app. " + OVER
        return shot, f"Patience left: {self.patience}/{self.patience_max}"

    async def close(self) -> None:
        if self.started:
            await self.device.stop()
        if not self.over and self.i:
            self._finish("abandoned")


def build_server(session: Session):
    from contextlib import asynccontextmanager

    from mcp.server.fastmcp import FastMCP, Image

    @asynccontextmanager
    async def lifespan(_server):
        try:
            yield {}
        finally:
            await session.close()

    mcp = FastMCP("device", lifespan=lifespan)

    async def _do(tool: str, args: dict, say: str):
        shot, msg = await session.act(tool, args, say)
        return [Image(data=shot, format="png"), msg] if shot else msg

    @mcp.tool()
    async def look(say: str):
        """Look at the screen without doing anything. `say`: what you say out loud right now."""
        return await _do("look", {}, say)

    @mcp.tool()
    async def tap(x: int, y: int, say: str):
        """Tap the screen at (x, y) in screenshot pixels. `say`: what you say out loud as you tap."""
        return await _do("tap", {"x": x, "y": y}, say)

    @mcp.tool()
    async def type_text(text: str, say: str):
        """Type text with the keyboard into whatever is focused (tap a field first)."""
        return await _do("type_text", {"text": text}, say)

    @mcp.tool()
    async def scroll(direction: str, say: str, amount: int = 400):
        """Scroll the screen 'up' or 'down' by `amount` pixels."""
        return await _do("scroll", {"direction": direction, "amount": amount}, say)

    @mcp.tool()
    async def back(say: str):
        """Go back (like the phone's back gesture)."""
        return await _do("back", {}, say)

    if hasattr(session.device, "reopen"):
        @mcp.tool()
        async def reopen(say: str):
            """Close this tab and open the app again in the same browser profile."""
            return await _do("reopen", {}, say)

    @mcp.tool()
    async def give_up(reason: str, say: str):
        """Stop trying and close the app, like a real person would when fed up or stuck."""
        return await _do("give_up", {"reason": reason}, say)

    @mcp.tool()
    async def done(summary: str, say: str):
        """Say you've finished what you came to do. `summary`: what you believe you accomplished."""
        return await _do("done", {"summary": summary}, say)

    return mcp


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--target-json", required=True)
    ap.add_argument("--patience", type=int, required=True)
    ap.add_argument("--url")
    a = ap.parse_args()
    import sys
    Path(a.run_dir).mkdir(parents=True, exist_ok=True)
    sys.stderr = open(Path(a.run_dir) / "device.log", "a", buffering=1)
    from .devices import make_device

    target = Target(**json.loads(Path(a.target_json).read_text()))
    session = Session(make_device(target, a.url), Path(a.run_dir), a.patience)
    build_server(session).run("stdio")


if __name__ == "__main__":
    main()
