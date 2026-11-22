"""Render a folder of HTML pages (or Claude Design .dc.html artboards) to PNG screens for stitching."""
from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path

from .config import data_dir

SHIM = "support.js"


def _shim_path() -> Path:
    return data_dir("claude-design") / SHIM


def _preview_width(text: str) -> int | None:
    m = re.search(r"data-props='([^']*)'", text)
    try:
        return int(json.loads(m.group(1))["$preview"]["width"]) if m else None
    except (ValueError, KeyError, TypeError):
        return None


async def capture_dir(src: str | Path, out: str | Path, width: int = 390, claude_design: bool = False,
                      only: list[str] | None = None) -> list[Path]:
    """Screenshot every *.html in `src` (full page) into `out/<stem>.png`, scaled to `width` CSS px."""
    from playwright.async_api import async_playwright

    from .devices._img import fit_width

    src, out = Path(src), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    pages = sorted(p for p in src.glob("*.htm*") if not only or p.name.split(".")[0] in only)
    made = []
    for img in sorted(p for p in src.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")):
        if only and img.stem not in only:
            continue
        (out / f"{img.stem}.png").write_bytes(fit_width(img.read_bytes(), width))
        made.append(out / f"{img.stem}.png")
    if not pages:
        return made
    with tempfile.TemporaryDirectory() as d:
        work = Path(d)
        for f in src.iterdir():
            if f.is_file():
                shutil.copy(f, work / f.name)
        if claude_design:
            shutil.copy(_shim_path(), work / SHIM)
        async with async_playwright() as pw:
            try:
                browser = await pw.chromium.launch(channel="chrome", headless=True)
            except Exception:
                browser = await pw.chromium.launch(headless=True)
            for p in pages:
                text = (work / p.name).read_text(errors="replace")
                if claude_design and SHIM not in text:
                    text = f'<script src="./{SHIM}"></script>' + text
                    (work / p.name).write_text(text)
                vw = _preview_width(text) or width
                page = await browser.new_page(viewport={"width": vw, "height": 844}, device_scale_factor=2)
                await page.goto((work / p.name).as_uri(), wait_until="load")
                if claude_design:
                    try:
                        await page.wait_for_selector("html[data-dc-ready]", timeout=5000)
                    except Exception:
                        pass
                await page.wait_for_timeout(300)
                png = await page.screenshot(full_page=True, animations="disabled")
                stem = p.name.split(".")[0]
                (out / f"{stem}.png").write_bytes(fit_width(png, width))
                made.append(out / f"{stem}.png")
                await page.close()
            await browser.close()
    return made


EXTRACT_JS = r"""() => {
  const out = [];
  const seen = new Set();
  const vis = (r) => r.width >= 6 && r.height >= 6;
  const lab = (el) => (el.getAttribute('aria-label') || el.innerText || el.value || el.placeholder || el.tagName).trim().replace(/\s+/g, ' ').slice(0, 50);
  for (const el of document.querySelectorAll('a[href], input, textarea, select, button, [role=button], [role=checkbox], [onclick]')) {
    if (el.closest('a[href]') && el.tagName !== 'A') continue;   // the enclosing link wins
    const r = el.getBoundingClientRect();
    if (!vis(r)) continue;
    const rect = [Math.round(r.left), Math.round(r.top + scrollY), Math.round(r.width), Math.round(r.height)];
    const key = rect.join(',');
    if (seen.has(key)) continue;
    seen.add(key);
    const tag = el.tagName.toLowerCase();
    const isText = (tag === 'input' && !['checkbox','radio','button','submit','range','color'].includes(el.type)) || tag === 'textarea';
    out.push({rect, label: lab(el), href: tag === 'a' ? el.getAttribute('href') : null, input: isText});
  }
  return {items: out, width: document.documentElement.scrollWidth};
}"""


async def stitch_dir(src: str | Path, out: str | Path, start: str, width: int = 390, claude_design: bool = False,
                     only: list[str] | None = None) -> Path:
    """Render linked HTML pages and auto-write flow.yaml: links -> hotspots, text fields -> inputs,
    controls without a link target -> recorded as unlinked (taps there become prototype gaps).
    Screen ids are neutral (s01, s02, ...); the name map goes to screens.map.yaml for the setup side only."""
    import yaml
    from playwright.async_api import async_playwright

    from .devices._img import fit_width

    src, out = Path(src), Path(out)
    (out / "screens").mkdir(parents=True, exist_ok=True)
    stem = lambda name: name.split("/")[-1].split("#")[0].split("?")[0].split(".")[0]
    pages = sorted(p for p in src.glob("*.htm*") if not only or stem(p.name) in only)
    names = [stem(p.name) for p in pages]
    if start not in names:
        raise ValueError(f"start page {start!r} not among {names}")
    order = [start] + [n for n in names if n != start]
    ids = {n: f"s{i + 1:02d}" for i, n in enumerate(order)}
    screens = {}
    with tempfile.TemporaryDirectory() as d:
        work = Path(d)
        for f in src.iterdir():
            if f.is_file():
                shutil.copy(f, work / f.name)
        if claude_design:
            shutil.copy(_shim_path(), work / SHIM)
        async with async_playwright() as pw:
            try:
                browser = await pw.chromium.launch(channel="chrome", headless=True)
            except Exception:
                browser = await pw.chromium.launch(headless=True)
            for p in pages:
                n = stem(p.name)
                text = (work / p.name).read_text(errors="replace")
                if claude_design and SHIM not in text:
                    (work / p.name).write_text(f'<script src="./{SHIM}"></script>' + text)
                vw = _preview_width(text) or width
                page = await browser.new_page(viewport={"width": vw, "height": 844}, device_scale_factor=2)
                await page.goto((work / p.name).as_uri(), wait_until="load")
                if claude_design:
                    try:
                        await page.wait_for_selector("html[data-dc-ready]", timeout=5000)
                    except Exception:
                        pass
                await page.wait_for_timeout(300)
                found = await page.evaluate(EXTRACT_JS)
                png = await page.screenshot(full_page=True, animations="disabled")
                await page.close()
                k = width / max(found["width"], 1)
                img = f"screens/{ids[n]}.png"
                (out / img).write_bytes(fit_width(png, width))
                hs = []
                for it in found["items"]:
                    rect = [round(v * k) for v in it["rect"]]
                    target = stem(it["href"]) if it["href"] else None
                    if it["input"]:
                        hs.append({"rect": rect, "input": f"f{len(hs) + 1}", "label": it["label"]})
                    elif target in ids:
                        hs.append({"rect": rect, "to": ids[target], "label": it["label"]})
                    else:
                        why = f"links to missing page {target}" if target else "no link"
                        hs.append({"rect": rect, "label": f"UNLINKED ({why}): {it['label']}"})
                screens[ids[n]] = {"image": img, "hotspots": hs}
            await browser.close()
    flow = {"start": ids[start], "width": width, "screens": screens}
    header = ("# Generated by `ux-swarm stitch`. Review with `ux-swarm preview`.\n"
              "# rect = [x, y, w, h] in CSS px. Hotspots labelled UNLINKED have no target: taps there are\n"
              "# logged as prototype gaps. Add `to: <screen id>` where you have the destination screen.\n")
    fp = out / "flow.yaml"
    fp.write_text(header + yaml.safe_dump(flow, sort_keys=False, allow_unicode=True, width=200))
    (out / "screens.map.yaml").write_text(yaml.safe_dump({ids[n]: n for n in order}, sort_keys=False))
    return fp
