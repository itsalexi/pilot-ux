import json
import re
from io import BytesIO

import httpx
import pytest
from PIL import Image, ImageDraw

from pilot_ux.config import Target
from pilot_ux.devices import make_device
from pilot_ux.proto import load_flow, preview_sheet, serve_proto, serve_static


@pytest.fixture
def flow_file(tmp_path):
    for name, color in (("HomeSecret", "white"), ("PaidAllSecret", "pink")):
        img = Image.new("RGB", (390, 844), color)
        ImageDraw.Draw(img).rectangle([50, 100, 250, 160], fill="green")
        img.save(tmp_path / f"{name}.png")
    (tmp_path / "flow.yaml").write_text(
        "start: home\n"
        "screens:\n"
        "  home:\n    image: HomeSecret.png\n    hotspots:\n"
        "      - {rect: [50, 100, 200, 60], to: paid_all, label: big green button}\n"
        "      - {rect: [50, 300, 250, 40], input: Name, label: name field}\n"
        "  paid_all:\n    image: PaidAllSecret.png\n    hotspots: []\n")
    return tmp_path / "flow.yaml"


def test_routes_are_opaque(flow_file, tmp_path):
    srv = serve_proto(load_flow(flow_file), log_dir=tmp_path)
    try:
        html = httpx.get(srv.url, follow_redirects=True).text
        for leak in ("home", "paid_all", "HomeSecret", "PaidAllSecret", "big green button", "flow"):
            assert leak not in srv.url
            assert leak not in html
        assert re.search(r"<title>\s*</title>", html)
    finally:
        srv.close()


async def test_hotspot_navigates_and_gap_logged(flow_file, tmp_path):
    srv = serve_proto(load_flow(flow_file), log_dir=tmp_path)
    dev = make_device(Target(kind="proto"), srv.url)
    await dev.start()
    try:
        home = await dev.screenshot()
        await dev.tap(300, 700)  # unmapped
        assert await dev.screenshot() == home
        gaps = [json.loads(l) for l in (tmp_path / "gaps.jsonl").read_text().splitlines()]
        assert gaps[0]["screen"] == "home" and gaps[0]["x"] == 300 and gaps[0]["y"] == 700
        await dev.tap(150, 130)
        assert await dev.screenshot() != home
    finally:
        await dev.stop()
        srv.close()


def test_static_server_hides_filenames(tmp_path):
    (tmp_path / "AllPaid.html").write_text('<html><head><title>AllPaid</title></head><body>done</body></html>')
    (tmp_path / "index.html").write_text('<html><head><title>Home</title></head><body><a href="AllPaid.html">go</a></body></html>')
    srv = serve_static(tmp_path, start="index.html")
    try:
        html = httpx.get(srv.url, follow_redirects=True).text
        assert "AllPaid" not in html and "AllPaid" not in srv.url
        link = re.search(r'href="([^"]+)"', html).group(1)
        assert httpx.get(httpx.URL(srv.url).join(link)).text.count("done") == 1
    finally:
        srv.close()


def test_preview_sheet_written(flow_file, tmp_path):
    out = tmp_path / "sheet.png"
    preview_sheet(load_flow(flow_file), out)
    assert Image.open(out).width >= 390 * 2


def test_task_start_overrides_flow_start(flow_file, tmp_path):
    from pilot_ux.runner import TargetHost
    from pilot_ux.config import Study, Target, Task
    from contextlib import ExitStack
    study = Study(name="s", target=Target(kind="proto", flow=str(flow_file)), personas=[],
                  tasks=[Task(id="t", goal="g", success_criteria=["c"], start="paid_all")])
    with TargetHost(study) as host, ExitStack() as st:
        url = host.url_for(tmp_path, st, study.tasks[0])
        html = httpx.get(url, follow_redirects=True).text
        flow = load_flow(flow_file)
        assert "/i/" in html
        img = re.search(r'src="(/i/[^"]+)"', html).group(1)
        assert httpx.get(httpx.URL(url).join(img)).content == (flow_file.parent / "PaidAllSecret.png").read_bytes()


async def test_auto_advance_screen(tmp_path):
    for name, color in (("home", "blue"), ("loading", "white"), ("ready", "pink")):
        Image.new("RGB", (390, 844), color).save(tmp_path / f"{name}.png")
    (tmp_path / "flow.yaml").write_text(
        "start: home\nscreens:\n"
        "  home: {image: home.png, hotspots: [{rect: [0, 0, 100, 100], to: loading}]}\n"
        "  loading: {image: loading.png, auto: {to: ready, after_ms: 300}}\n"
        "  ready: {image: ready.png}\n")
    srv = serve_proto(load_flow(tmp_path / "flow.yaml"))
    dev = make_device(Target(kind="proto"), srv.url)
    try:
        await dev.start()
        page = dev._page
        home = await dev.screenshot()
        # Hold the page's clock while the device waits for its new screen to settle.
        await page.clock.install(time="2025-01-01T00:00:00Z")
        await page.clock.pause_at("2025-01-01T00:01:00Z")
        await dev.tap(50, 50)
        loading_url = page.url
        await page.clock.run_for(299)
        assert Image.open(BytesIO(await dev.screenshot())).getpixel((195, 422)) == (255, 255, 255)

        await page.clock.run_for(1)
        await page.wait_for_url(lambda url: url != loading_url, timeout=5000)
        ready = await dev.screenshot()
        assert Image.open(BytesIO(ready)).getpixel((195, 422)) == (255, 192, 203)

        await dev.back()
        assert await dev.screenshot() == home
        await page.go_forward()
        assert await dev.screenshot() == ready
    finally:
        await dev.stop()
        srv.close()
