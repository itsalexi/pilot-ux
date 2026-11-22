import re
import shutil

import pytest

from ux_swarm import runner
from ux_swarm.config import Study, Target


def study_for(**target):
    return Study(name="test", target=Target(**target), tasks=[], personas=[])


@pytest.mark.parametrize("target", [
    {"kind": "url", "url": "https://example.test/demo"},
    {"kind": "ios", "app_bundle": "example.demo"},
])
def test_uninspectable_target_needs_explicit_build_identity(tmp_path, target):
    assert runner.target_build(study_for(**target), tmp_path) is None
    assert runner.target_build(study_for(**target, build_id="v7"), tmp_path) == "id:v7"


@pytest.mark.parametrize(("kind", "path_field", "dirname"), [
    ("static", "folder", "web"),
    ("ios", "ios_app_path", "Demo.app"),
])
def test_local_build_content_survives_relocation_and_detects_edits(tmp_path, kind, path_field, dirname):
    original = tmp_path / "first" / dirname
    original.mkdir(parents=True)
    (original / "page.html").write_text("alpha")
    (original / "asset.bin").write_bytes(b"\x00\xff")
    copy = tmp_path / "second" / dirname
    shutil.copytree(original, copy)
    out = tmp_path / "results"

    first = runner.target_build(study_for(kind=kind, **{path_field: str(original)}), out)
    relocated = study_for(kind=kind, **{path_field: str(copy)})
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", first)
    assert runner.target_build(relocated, out) == first
    (copy / "asset.bin").rename(copy / "moved.bin")
    assert runner.target_build(relocated, out) != first
    (copy / "moved.bin").rename(copy / "asset.bin")
    (copy / "page.html").write_text("bravo")  # same byte length, different content
    assert runner.target_build(relocated, out) != first


def test_static_fingerprint_excludes_nested_outputs_and_tooling(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("Hello")
    out = site / "experiment-results"
    study = study_for(kind="static", folder=str(site))
    original = runner.target_build(study, out)
    for indirect in (out, site / ".git", site / "node_modules"):
        indirect.mkdir()
        (indirect / "file").write_text("Changes independently of the app")
    sibling_run = site / "previous-study"
    sibling_run.mkdir()
    (sibling_run / "study.lock.json").write_text("{}")
    (sibling_run / "report.html").write_text("Earlier observations")
    assert runner.target_build(study, out) == original


def test_proto_tracks_flow_and_unique_referenced_images_only(tmp_path, monkeypatch):
    flow = tmp_path / "flow.yaml"
    flow.write_text("start: a\nscreens:\n  a: {image: frame.png}\n  b: {image: frame.png}\n")
    image = tmp_path / "frame.png"
    image.write_bytes(b"image one")
    monkeypatch.setattr(runner, "_BUILD_MAX_FILES", 2)
    out = tmp_path / "results"
    study = study_for(kind="proto", flow=str(flow))
    original = runner.target_build(study, out)
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", original)
    (tmp_path / "unused.png").write_bytes(b"unused")
    assert runner.target_build(study, out) == original
    image.write_bytes(b"image two")
    assert runner.target_build(study, out) != original
    image.write_bytes(b"image one")
    flow.write_text(flow.read_text().replace("start: a", "start: b"))
    assert runner.target_build(study, out) != original


def test_escaping_static_symlink_requires_explicit_build_id(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("Outside the target.")
    (site / "asset.txt").symlink_to(outside)
    with pytest.raises(ValueError, match=r"target\.build_id"):
        runner.target_build(study_for(kind="static", folder=str(site)), tmp_path / "out")


def test_internal_directory_alias_and_its_contents_affect_fingerprint(tmp_path):
    site = tmp_path / "site"
    source = site / "assets"
    source.mkdir(parents=True)
    (source / "menu.js").write_text("version one")
    study = study_for(kind="static", folder=str(site))
    out = tmp_path / "out"
    original = runner.target_build(study, out)
    (site / "public").symlink_to("assets", target_is_directory=True)
    aliased = runner.target_build(study, out)
    assert aliased != original
    (source / "menu.js").write_text("version two")
    assert runner.target_build(study, out) != aliased


def test_alias_to_an_excluded_dependency_requires_explicit_build_id(tmp_path):
    site = tmp_path / "site"
    dependency = site / "node_modules" / "widget"
    dependency.mkdir(parents=True)
    (dependency / "widget.js").write_text("export default 'widget';")
    (site / "vendor").symlink_to("node_modules/widget", target_is_directory=True)
    with pytest.raises(ValueError, match=r"target\.build_id"):
        runner.target_build(study_for(kind="static", folder=str(site)), tmp_path / "out")


@pytest.mark.parametrize(("limit", "value"), [("_BUILD_MAX_FILES", 1), ("_BUILD_MAX_BYTES", 7)])
def test_oversized_target_can_supply_an_explicit_build_id(tmp_path, monkeypatch, limit, value):
    monkeypatch.setattr(runner, limit, value)
    (tmp_path / "a.txt").write_bytes(b"1234")
    (tmp_path / "b.txt").write_bytes(b"5678")
    target = {"kind": "static", "folder": str(tmp_path)}
    out = tmp_path / "out"
    with pytest.raises(ValueError, match=r"target\.build_id"):
        runner.target_build(study_for(**target), out)
    assert runner.target_build(study_for(**target, build_id="v7"), out) == "id:v7"
