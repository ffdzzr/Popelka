"""popelka - reverse-engineering toolkit for the Concept VR3125 robot vacuum.

Core protocol modules (``aa``, ``dp``, ``commands``) are pure stdlib and are
imported eagerly. ``maps`` and ``cloud`` pull optional dependencies (lz4, urllib
extras), so they are imported lazily - this keeps the capture tools usable in a
minimal environment.
"""

from __future__ import annotations

import importlib

__version__ = "0.1.0"

from . import aa, commands, dp, droid, voice  # noqa: F401

_LAZY = {"maps", "cloud", "tuya", "replay"}

__all__ = ["aa", "commands", "dp", "droid", "voice", "cloud", "maps", "tuya", "replay"]


def __getattr__(name: str):
    if name in _LAZY:
        module = importlib.import_module(f".{name}", __name__)
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
