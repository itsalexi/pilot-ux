import io
from PIL import Image
from ux_swarm.config import Target
from ux_swarm.device_mcp import Session, build_server
from ux_swarm.devices import make_device


async def test_web_device_tap_changes_page(site_url):
    dev = make_device(Target(kind="url", url=site_url))
    await dev.start()
    try:
        before = await dev.screenshot()
        assert Image.open(io.BytesIO(before)).size == (390, 844)
        await dev.tap(150, 130)
        after = await dev.screenshot()
        assert after != before
        await dev.back()
        again = await dev.screenshot()
        assert again == before
    finally:
        await dev.stop()


async def test_web_device_types_into_focused_field(site_url):
    dev = make_device(Target(kind="url", url=site_url))
    await dev.start()
    try:
        before = await dev.screenshot()
        await dev.tap(150, 320)
        await dev.type_text("Ana")
        assert await dev.screenshot() != before
    finally:
        await dev.stop()


async def test_reopen_starts_at_entry_with_saved_data_and_a_fresh_tab(site_url, tmp_path):
    dev = make_device(Target(kind="url", url=site_url))
    session = Session(dev, tmp_path, patience=10)
    assert "reopen" in [tool.name for tool in await build_server(session).list_tools()]
    try:
        await session.act("look", {}, "Opening the app.")
        await session.act("tap", {"x": 150, "y": 130}, "Going to the next page.")
        old_tab = dev._page
        assert old_tab.url.endswith("two.html")
        await old_tab.evaluate("""() => {
            localStorage.setItem('saved-name', 'Basil');
            sessionStorage.setItem('draft', 'unsaved');
            window.unsaved = true;
        }""")
        frame, _ = await session.act("reopen", {}, "Checking what stayed saved.")
        assert frame and old_tab.is_closed()
        assert dev._page.url == site_url
        assert await dev._page.evaluate("""() => [
            localStorage.getItem('saved-name'), sessionStorage.getItem('draft'), typeof window.unsaved
        ]""") == ["Basil", None, "undefined"]
    finally:
        await session.close()
