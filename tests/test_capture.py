from PIL import Image

from pilot_ux.capture import capture_dir


async def test_capture_dir_renders_each_page(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "A.html").write_text("<body style='margin:0'><div style='width:390px;height:1000px;background:red'></div>")
    (src / "B.dc.html").write_text(
        "<x-dc><div style='width:390px;height:844px;background:#00f'>{{ title }}</div></x-dc>"
        "<script type='text/x-dc' data-dc-script data-props='{\"$preview\":{\"width\":390,\"height\":844}}'>"
        "class Component extends DCLogic { renderVals(){ return {title: 'hi'} } }</script>")
    out = tmp_path / "out"
    made = await capture_dir(src, out, claude_design=True)
    assert sorted(p.name for p in made) == ["A.png", "B.png"]
    a = Image.open(out / "A.png")
    assert a.size == (390, 1000)  # full page, CSS px
    assert Image.open(out / "B.png").getpixel((10, 10))[2] > 200


async def test_stitch_extracts_links_inputs_and_unlinked_buttons(tmp_path):
    import yaml
    from pilot_ux.capture import stitch_dir
    from pilot_ux.proto import load_flow
    src = tmp_path / "src"
    src.mkdir()
    (src / "HomeSecret.html").write_text(
        "<body style='margin:0'><a href='PaidAll.html' aria-label='Go' "
        "style='position:absolute;left:10px;top:20px;width:100px;height:40px;display:block'></a>"
        "<input style='position:absolute;left:10px;top:100px;width:200px;height:30px'>"
        "<button style='position:absolute;left:10px;top:200px;width:80px;height:30px'>Nope</button></body>")
    (src / "PaidAll.html").write_text("<body style='margin:0'>done</body>")
    out = tmp_path / "proto"
    flow_path = stitch_dir_sync = await stitch_dir(src, out, start="HomeSecret")
    flow = load_flow(flow_path)
    raw = flow_path.read_text()
    assert "HomeSecret" not in yaml.safe_load(raw)["screens"] and flow.start == "s01"
    hs = flow.screens["s01"].hotspots
    link = [h for h in hs if h.to][0]
    assert link.to == "s02" and link.rect == (10, 20, 100, 40)
    assert any(h.input is not None and h.rect == (10, 100, 200, 30) for h in hs)
    assert any(h.to is None and h.input is None and "Nope" in h.label for h in hs)
    assert (out / "screens.map.yaml").exists()


async def test_capture_resizes_existing_images(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    Image.new("RGB", (1170, 2532), "white").save(src / "shot.png")
    made = await capture_dir(src, tmp_path / "out")
    assert [p.name for p in made] == ["shot.png"]
    assert Image.open(made[0]).size == (390, 844)
