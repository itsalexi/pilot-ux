"""Playwright-driven browser in a phone-sized viewport. No URL bar, no DOM access exposed."""
from __future__ import annotations

import asyncio
import os
from typing import Literal

from playwright.async_api import async_playwright

from ..config import Target
from ._img import fit_width


class WebDevice:
    def __init__(self, target: Target, url: str | None):
        if not url:
            raise ValueError("web target needs a url")
        self.target, self.url = target, url
        self._pw = self._browser = self._context = self._page = None

    async def start(self) -> None:
        self._pw = await async_playwright().start()
        channel = os.environ.get("UX_SWARM_CHROME_CHANNEL", "chrome")
        try:
            self._browser = await self._pw.chromium.launch(channel=channel, headless=True)
        except Exception:
            self._browser = await self._pw.chromium.launch(headless=True)
        w, h = self.target.viewport
        state = os.environ.get("UX_SWARM_STORAGE_STATE")
        self._context = await self._browser.new_context(
            viewport={"width": w, "height": h},
            device_scale_factor=self.target.scale,
            is_mobile=self.target.mobile,
            has_touch=self.target.mobile,
            storage_state=state if state and os.path.exists(state) else None,
        )
        await self._open_entry()

    async def _open_entry(self) -> None:
        self._page = await self._context.new_page()
        await self._page.goto(self.url, wait_until="domcontentloaded")
        await self._settle()

    async def reopen(self) -> None:
        """Close the tab and reopen the app's entry point in the same browser profile."""
        await self._page.close()
        await self._open_entry()

    async def stop(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    async def _settle(self) -> None:
        try:
            await self._page.wait_for_load_state("networkidle", timeout=1500)
        except Exception:
            pass
        await asyncio.sleep(0.25)

    async def screenshot(self) -> bytes:
        png = await self._page.screenshot(animations="disabled", caret="initial")
        return fit_width(png, self.target.viewport[0])

    async def tap(self, x: int, y: int) -> None:
        if self.target.mobile:
            await self._page.touchscreen.tap(x, y)
        else:
            await self._page.mouse.click(x, y)
        await self._settle()

    async def type_text(self, text: str) -> None:
        await self._page.keyboard.type(text, delay=20)
        await self._settle()

    async def scroll(self, direction: Literal["up", "down"], amount: int) -> None:
        w, h = self.target.viewport
        await self._page.mouse.move(w / 2, h / 2)
        await self._page.mouse.wheel(0, amount if direction == "down" else -amount)
        await self._settle()

    async def back(self) -> None:
        await self._page.go_back(wait_until="domcontentloaded")
        await self._settle()
