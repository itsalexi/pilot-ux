from __future__ import annotations

from ..config import Target
from .base import Device


def make_device(target: Target, url: str | None = None) -> Device:
    """Build the device for a target. `url` overrides target.url (used for served prototypes)."""
    if target.kind == "ios":
        from .ios import IOSDevice
        return IOSDevice(target)
    from .web import WebDevice
    return WebDevice(target, url or target.url)


__all__ = ["Device", "make_device"]
