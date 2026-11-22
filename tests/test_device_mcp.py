import json

from ux_swarm.device_mcp import Session, TOOL_NAMES, build_server


class FakeDevice:
    """Screen is a counter; tap at y<100 is a dead spot (screen unchanged)."""
    def __init__(self):
        self.screen = 0

    async def start(self): pass
    async def stop(self): pass
    async def screenshot(self): return f"png{self.screen}".encode()
    async def tap(self, x, y):
        if y >= 100:
            self.screen += 1
    async def type_text(self, text): self.screen += 1
    async def scroll(self, direction, amount): pass
    async def back(self): self.screen -= 1


def steps(run_dir):
    return [json.loads(l) for l in (run_dir / "steps.jsonl").read_text().splitlines()]


async def test_unchanged_screen_costs_double(tmp_path):
    s = Session(FakeDevice(), tmp_path, patience=10)
    await s.act("look", {}, "first look")
    _, msg = await s.act("tap", {"x": 10, "y": 10}, "tap dead spot")
    assert "8/10" in msg
    _, msg = await s.act("tap", {"x": 10, "y": 200}, "tap button")
    assert "7/10" in msg
    log = steps(tmp_path)
    assert [l["changed"] for l in log] == [True, False, True]
    assert log[1]["thought"] == "tap dead spot"
    assert (tmp_path / log[2]["shot"]).read_bytes() == b"png1"


async def test_patience_exhaustion_writes_outcome(tmp_path):
    s = Session(FakeDevice(), tmp_path, patience=3)
    await s.act("look", {}, "hi")
    await s.act("tap", {"x": 1, "y": 1}, "nothing")
    _, msg = await s.act("tap", {"x": 1, "y": 1}, "nothing again")
    assert "run out of patience" in msg
    out = json.loads((tmp_path / "outcome.json").read_text())
    assert out["status"] == "out_of_patience"
    _, msg = await s.act("tap", {"x": 1, "y": 200}, "after end")
    assert "over" in msg.lower()
    assert len(steps(tmp_path)) == 3


async def test_give_up_and_done_end_session(tmp_path):
    s = Session(FakeDevice(), tmp_path, patience=10)
    await s.act("give_up", {"reason": "too confusing"}, "ugh")
    out = json.loads((tmp_path / "outcome.json").read_text())
    assert out == {"status": "gave_up", "reason": "too confusing", "steps": 1}


def test_tool_names_exact():
    assert TOOL_NAMES == ["look", "tap", "type_text", "scroll", "back", "reopen", "give_up", "done"]
    for name in TOOL_NAMES:
        for banned in ("url", "dom", "eval", "js", "source", "navigate", "html"):
            assert banned not in name


async def test_device_without_reopen_does_not_offer_it(tmp_path):
    server = build_server(Session(FakeDevice(), tmp_path, patience=10))
    names = [tool.name for tool in await server.list_tools()]
    assert names == [name for name in TOOL_NAMES if name != "reopen"]
