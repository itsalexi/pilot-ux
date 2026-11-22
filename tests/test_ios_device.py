import plistlib
from unittest.mock import AsyncMock

import pytest

from ux_swarm.config import Target
from ux_swarm.devices import ios


def device(monkeypatch, path):
    monkeypatch.setattr(ios.shutil, "which", lambda _: "/opt/homebrew/bin/axe")
    monkeypatch.setattr(ios.asyncio, "sleep", AsyncMock())
    return ios.IOSDevice(Target(kind="ios", udid="study-sim", app_bundle="app.demo", ios_app_path=str(path),
                                launch_args=["-completedOnboarding", "YES"]))


@pytest.mark.parametrize("installed", [True, False])
async def test_session_starts_with_fresh_container(tmp_path, monkeypatch, installed):
    (tmp_path / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "app.demo"}))
    apps = {"app.demo": {}} if installed else {}
    run = AsyncMock(side_effect=[b"{ }", plistlib.dumps(apps), *([b""] if installed else []), b"", b""])
    monkeypatch.setattr(ios, "_run", run)
    await device(monkeypatch, tmp_path).start()
    calls = [c.args for c in run.await_args_list]
    uninstall = ("xcrun", "simctl", "uninstall", "study-sim", "app.demo")
    assert (uninstall in calls) == installed
    assert calls[-2:] == [("xcrun", "simctl", "install", "study-sim", str(tmp_path)),
                          ("xcrun", "simctl", "launch", "--terminate-running-process", "study-sim", "app.demo",
                           "-completedOnboarding", "YES")]


async def test_invalid_bundle_does_not_remove_installed_app(tmp_path, monkeypatch):
    run = AsyncMock()
    monkeypatch.setattr(ios, "_run", run)
    sim = device(monkeypatch, tmp_path)
    with pytest.raises(FileNotFoundError):
        await sim.start()
    (tmp_path / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "wrong.app"}))
    with pytest.raises(ValueError, match="matching app_bundle"):
        await sim.start()
    run.assert_not_awaited()
