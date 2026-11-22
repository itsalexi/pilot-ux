"""iOS Simulator via AXe (https://github.com/cameroncooke/AXe) + simctl. macOS only."""
from __future__ import annotations

import asyncio
import plistlib
import shutil
import tempfile
from pathlib import Path
from typing import Literal

from ..config import Target
from ._img import fit_width


async def _run(*args: str, stdin: bytes | None = None) -> bytes:
    proc = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.PIPE if stdin is not None else None,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await proc.communicate(stdin)
    if proc.returncode:
        raise RuntimeError(f"{args[0]} failed: {err.decode()[-400:]}")
    return out


class IOSDevice:
    def __init__(self, target: Target):
        if not shutil.which("axe"):
            raise RuntimeError("iOS target needs AXe: brew install cameroncooke/axe/axe")
        self.target = target
        self.udid = target.udid or "booted"

    async def _udid(self) -> str:
        if self.udid != "booted":
            return self.udid
        import json
        data = json.loads(await _run("xcrun", "simctl", "list", "devices", "booted", "-j"))
        for devs in data["devices"].values():
            for d in devs:
                if d.get("state") == "Booted":
                    self.udid = d["udid"]
                    return self.udid
        raise RuntimeError("no booted simulator; boot one and install the app first")

    async def start(self) -> None:
        udid = await self._udid()
        bundle = self.target.app_bundle
        if self.target.ios_app_path:
            path = Path(self.target.ios_app_path)
            info = plistlib.loads((path / "Info.plist").read_bytes())
            if not bundle or info.get("CFBundleIdentifier") != bundle:
                raise ValueError("ios_app_path must point to the simulator app matching app_bundle")
            apps = await _run("xcrun", "simctl", "listapps", udid)
            # simctl listapps emits an old-style ASCII plist on some Xcode versions.
            installed = plistlib.loads(await _run("plutil", "-convert", "xml1", "-o", "-", "-", stdin=apps))
            if bundle in installed:
                await _run("xcrun", "simctl", "uninstall", udid, bundle)
            await _run("xcrun", "simctl", "install", udid, str(path))
        if bundle:
            await _run("xcrun", "simctl", "launch", "--terminate-running-process", udid, bundle, *self.target.launch_args)
            await asyncio.sleep(2.0)

    async def stop(self) -> None:
        pass

    async def screenshot(self) -> bytes:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.png"
            await _run("xcrun", "simctl", "io", await self._udid(), "screenshot", "--type=png", str(p))
            return fit_width(p.read_bytes(), self.target.viewport[0])

    async def tap(self, x: int, y: int) -> None:
        await _run("axe", "tap", "-x", str(x), "-y", str(y), "--udid", await self._udid())
        await asyncio.sleep(0.8)

    async def type_text(self, text: str) -> None:
        await _run("axe", "type", text, "--udid", await self._udid())
        await asyncio.sleep(0.5)

    async def scroll(self, direction: Literal["up", "down"], amount: int) -> None:
        w, h = self.target.viewport
        y0, y1 = (h * 0.7, h * 0.7 - amount) if direction == "down" else (h * 0.3, h * 0.3 + amount)
        y1 = max(60, min(h - 60, y1))
        await _run("axe", "swipe", "--start-x", str(w // 2), "--start-y", str(int(y0)),
                   "--end-x", str(w // 2), "--end-y", str(int(y1)), "--udid", await self._udid())
        await asyncio.sleep(0.8)

    async def back(self) -> None:
        h = self.target.viewport[1]
        await _run("axe", "swipe", "--start-x", "5", "--start-y", str(h // 2),
                   "--end-x", "300", "--end-y", str(h // 2), "--udid", await self._udid())
        await asyncio.sleep(0.8)
