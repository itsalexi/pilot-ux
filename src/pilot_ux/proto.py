"""Clickable prototypes for persona agents.

- serve_proto: static screen images + hotspot map (flow.yaml) -> opaque-route web prototype.
  Taps outside hotspots leave the screen unchanged and are logged to gaps.jsonl as prototype gaps.
- serve_static: a folder of linked HTML pages served under opaque routes, titles blanked.
- preview_sheet: contact sheet of every screen with numbered hotspots, for a human check before a run.
"""
from __future__ import annotations

import hashlib
import html
import json
import mimetypes
import re
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml
from pydantic import BaseModel


class Hotspot(BaseModel):
    rect: tuple[int, int, int, int]  # x, y, w, h in CSS px of the 390-wide screen
    to: str | None = None
    input: str | None = None  # renders a text field; value is the hidden field name
    label: str = ""  # for humans only, never served


class Auto(BaseModel):
    to: str
    after_ms: int = 2500


class Screen(BaseModel):
    image: str
    hotspots: list[Hotspot] = []
    auto: Auto | None = None  # e.g. a loading screen that moves on by itself


class Flow(BaseModel):
    start: str
    width: int = 390
    screens: dict[str, Screen]
    base: str = "."

    def check(self) -> list[str]:
        errs = []
        if self.start not in self.screens:
            errs.append(f"start {self.start!r} is not a screen")
        for sid, s in self.screens.items():
            if not (Path(self.base) / s.image).exists():
                errs.append(f"{sid}: image missing {s.image}")
            for h in s.hotspots:
                if h.to and h.to not in self.screens:
                    errs.append(f"{sid}: hotspot {h.label!r} -> unknown screen {h.to!r}")
            if s.auto and s.auto.to not in self.screens:
                errs.append(f"{sid}: auto -> unknown screen {s.auto.to!r}")
        return errs


def load_flow(path: str | Path) -> Flow:
    path = Path(path).resolve()
    flow = Flow(**yaml.safe_load(path.read_text()), base=str(path.parent))
    errs = flow.check()
    if errs:
        raise ValueError("flow.yaml problems:\n  " + "\n  ".join(errs))
    return flow


def _h(s: str, salt: str = "") -> str:
    return hashlib.sha1((salt + s).encode()).hexdigest()[:8]


@dataclass
class Served:
    url: str
    server: ThreadingHTTPServer

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def _serve(handler_cls) -> Served:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return Served(f"http://127.0.0.1:{srv.server_port}/", srv)


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width={w}, initial-scale=1"><title> </title>
<style>html,body{{margin:0;padding:0;background:#fff}}#s{{position:relative;width:{w}px}}
#s img{{display:block;width:{w}px;user-select:none;-webkit-user-drag:none}}
.h{{position:absolute;display:block;-webkit-tap-highlight-color:transparent}}
.i{{position:absolute;border:0;background:transparent;font:17px -apple-system,system-ui,sans-serif;color:#111;padding:0 8px;box-sizing:border-box;outline:none}}</style>
</head><body><div id="s"><img src="/i/{img}.png" alt="">{spots}</div>
<script>
document.addEventListener('click',function(e){{
  if(e.target.closest('.h,.i'))return;
  navigator.sendBeacon('/gap',JSON.stringify({{r:'{route}',x:Math.round(e.clientX),y:Math.round(e.clientY),sy:Math.round(scrollY)}}));
}},true);
{auto}
</script></body></html>"""


def serve_proto(flow: Flow, log_dir: str | Path | None = None, salt: str = "") -> Served:
    routes = {sid: _h(sid, salt) for sid in flow.screens}
    back = {v: k for k, v in routes.items()}
    images = {_h(s.image, salt + "img"): Path(flow.base) / s.image for s in flow.screens.values()}
    log = Path(log_dir) / "gaps.jsonl" if log_dir else None
    lock = threading.Lock()

    def page(sid: str) -> bytes:
        s = flow.screens[sid]
        spots = []
        for h in s.hotspots:
            x, y, w, hh = h.rect
            style = f"left:{x}px;top:{y}px;width:{w}px;height:{hh}px"
            if h.input is not None:
                spots.append(f'<input class="i" style="{style}" autocomplete="off" aria-label="">')
            elif h.to:
                spots.append(f'<a class="h" style="{style}" href="/s/{routes[h.to]}"></a>')
        auto = (f"setTimeout(function(){{location.replace('/s/{routes[s.auto.to]}')}},{s.auto.after_ms});"
                if s.auto else "")
        return PAGE.format(w=flow.width, img=_h(s.image, salt + "img"), spots="".join(spots),
                           route=routes[sid], auto=auto).encode()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code: int, body: bytes, ctype: str = "text/html; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            p = self.path.split("?")[0]
            if p == "/":
                self.send_response(302)
                self.send_header("Location", f"/s/{routes[flow.start]}")
                self.end_headers()
            elif p.startswith("/s/") and p[3:] in back:
                self._send(200, page(back[p[3:]]))
            elif p.startswith("/i/") and p[3:-4] in images:
                self._send(200, images[p[3:-4]].read_bytes(), "image/png")
            else:
                self._send(404, b"")

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0)
            if self.path == "/gap" and log:
                try:
                    d = json.loads(body)
                    rec = {"ts": time.time(), "screen": back.get(d.get("r"), "?"),
                           "x": d.get("x"), "y": d.get("y"), "scroll_y": d.get("sy", 0)}
                    with lock, open(log, "a") as f:
                        f.write(json.dumps(rec) + "\n")
                except Exception:
                    pass
            self._send(204, b"")

    return _serve(H)


_LINK = re.compile(r'''(href|src|action)=(["'])([^"'#?]+\.html?)([#?][^"']*)?\2''', re.I)


def serve_static(folder: str | Path, start: str = "index.html", salt: str = "") -> Served:
    folder = Path(folder).resolve()
    pages = {p.relative_to(folder).as_posix(): p for p in folder.rglob("*.htm*")}
    if start not in pages:
        raise ValueError(f"start page {start!r} not found in {folder}")
    routes = {name: _h(name, salt) for name in pages}
    back = {v: k for k, v in routes.items()}

    def rewrite(name: str, text: str) -> str:
        here = Path(name).parent

        def sub(m):
            target = (here / m.group(3)).as_posix()
            target = str(Path(target)).replace("\\", "/")
            if target in routes:
                return f'{m.group(1)}={m.group(2)}/p/{routes[target]}{m.group(4) or ""}{m.group(2)}'
            return m.group(0)
        text = _LINK.sub(sub, text)
        return re.sub(r"<title>.*?</title>", "<title> </title>", text, flags=re.S | re.I)

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            p = self.path.split("?")[0]
            if p == "/":
                self.send_response(302)
                self.send_header("Location", f"/p/{routes[start]}")
                self.end_headers()
                return
            if p.startswith("/p/") and p[3:] in back:
                name = back[p[3:]]
                body = rewrite(name, pages[name].read_text(errors="replace")).encode()
                return self._send(200, body, "text/html; charset=utf-8")
            rel = p.removeprefix("/p/").lstrip("/")
            f = (folder / rel).resolve()
            if f.is_file() and folder in f.parents and not f.suffix.lower().startswith(".htm"):
                return self._send(200, f.read_bytes(), mimetypes.guess_type(f.name)[0] or "application/octet-stream")
            self._send(404, b"", "text/plain")

    return _serve(H)


def preview_sheet(flow: Flow, out: str | Path, cols: int = 4) -> Path:
    from PIL import Image, ImageDraw

    tiles = []
    for sid, s in flow.screens.items():
        img = Image.open(Path(flow.base) / s.image).convert("RGB")
        img = img.resize((flow.width, round(img.height * flow.width / img.width)))
        d = ImageDraw.Draw(img)
        legend = [f"[{sid}]{' (start)' if sid == flow.start else ''}"]
        for n, h in enumerate(s.hotspots, 1):
            x, y, w, hh = h.rect
            color = (0, 120, 255) if h.input is not None else (230, 0, 0)
            d.rectangle([x, y, x + w, y + hh], outline=color, width=2)
            d.text((x + 3, y + 2), str(n), fill=color)
            legend.append(f"{n}. {h.label or '?'} -> {h.to or ('input ' + str(h.input))}")
        lh = 14 * len(legend) + 10
        tile = Image.new("RGB", (flow.width, img.height + lh), "white")
        tile.paste(img, (0, 0))
        td = ImageDraw.Draw(tile)
        for i, line in enumerate(legend):
            td.text((4, img.height + 4 + 14 * i), line, fill="black")
        tiles.append(tile)
    cols = min(cols, max(len(tiles), 2))
    rows = (len(tiles) + cols - 1) // cols
    th = max(t.height for t in tiles)
    sheet = Image.new("RGB", (cols * (flow.width + 10), rows * (th + 10)), (200, 200, 200))
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % cols) * (flow.width + 10), (i // cols) * (th + 10)))
    out = Path(out)
    sheet.save(out)
    return out
