"""
Ce module réexporte les classes de model.window pour rétrocompatibilité
et faciliter les imports directs (ex: `from window import Window`).
"""

from model.window import (
    IWindow,
    WindowGeometry,
    LinuxWindow,
    WindowsWindow,
    MacWindow,
    Window,
    WindowFactory,
    LinuxWindowFactory,
    WindowsWindowFactory,
    MacWindowFactory,
)

__all__ = [
    "IWindow",
    "WindowGeometry",
    "LinuxWindow",
    "WindowsWindow",
    "MacWindow",
    "Window",
    "WindowFactory",
    "LinuxWindowFactory",
    "WindowsWindowFactory",
    "MacWindowFactory",
]