"""Pilot: test any UX like real first-time users."""
import os


def env(name: str, default: str | None = None) -> str | None:
    """Read PILOT_<name>, falling back to the legacy UX_SWARM_<name>."""
    for key in (f"PILOT_{name}", f"UX_SWARM_{name}"):
        if (value := os.environ.get(key)) is not None:
            return value
    return default
