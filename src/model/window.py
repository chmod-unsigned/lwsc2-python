"""
Façade Window et réexports de rétrocompatibilité.
Permet d'utiliser `from model.window import Window, IWindow, ...` de manière transparente.
"""

from typing import Optional, List, Any

from .geometry import WindowGeometry
from .base import IWindow
from .linux import LinuxWindow
from .windows import WindowsWindow
from .mac import MacWindow
from .factory import (
    WindowFactory,
    LinuxWindowFactory,
    WindowsWindowFactory,
    MacWindowFactory,
)


class Window(IWindow):
    """
    Façade pratique et universelle pour manipuler une fenêtre et son arborescence quel que soit l'OS.
    Délègue les appels à l'implémentation spécifique (LinuxWindow, WindowsWindow, MacWindow).
    Peut être instanciée par son PID ou par son titre (ou les deux).
    """

    def __init__(
        self,
        pid: Optional[int | str] = None,
        title: str = "",
        impl: Optional[IWindow] = None,
    ):
        if isinstance(pid, str) and not title:
            title = pid
            pid = None
        super().__init__(pid=pid, title=title)
        self._impl = impl if impl is not None else WindowFactory.create(pid=self.pid, title=self.title)

    @property
    def pid(self) -> Optional[int]:
        if hasattr(self, "_impl") and self._impl is not None:
            return self._impl.pid
        return getattr(self, "_pid", None)

    @pid.setter
    def pid(self, value: Optional[int]) -> None:
        self._pid = value
        if hasattr(self, "_impl") and self._impl is not None:
            self._impl.pid = value

    @property
    def title(self) -> str:
        if hasattr(self, "_impl") and self._impl is not None:
            return self._impl.title
        return getattr(self, "_title", "")

    @title.setter
    def title(self, value: str) -> None:
        self._title = value
        if hasattr(self, "_impl") and self._impl is not None:
            self._impl.title = value

    @property
    def window_id(self) -> Optional[str]:
        if hasattr(self, "_impl") and self._impl is not None:
            return self._impl.window_id
        return getattr(self, "_window_id", None)

    @window_id.setter
    def window_id(self, value: Optional[str]) -> None:
        self._window_id = value
        if hasattr(self, "_impl") and self._impl is not None:
            self._impl.window_id = value

    @property
    def children(self) -> List[IWindow]:
        if hasattr(self, "_impl") and self._impl is not None:
            return self._impl.children
        return getattr(self, "_children", [])

    @children.setter
    def children(self, value: List[IWindow]) -> None:
        self._children = value
        if hasattr(self, "_impl") and self._impl is not None:
            self._impl.children = value

    def exists(self) -> bool:
        return self._impl.exists()

    def get_geometry(self, include_decorations: bool = False) -> Optional[WindowGeometry]:
        return self._impl.get_geometry(include_decorations=include_decorations)

    def activate(self) -> bool:
        return self._impl.activate()

    def capture(
        self, output_path: Optional[str] = None, include_decorations: bool = False
    ) -> Optional[Any]:
        return self._impl.capture(output_path=output_path, include_decorations=include_decorations)

    def get_tree(self) -> IWindow:
        """Construit et retourne l'arborescence des sous-fenêtres de cette fenêtre."""
        return self._impl.get_tree()

    def tree_str(self, depth: int = 0) -> str:
        return self._impl.tree_str(depth=depth)

    def click(
        self,
        x: int,
        y: int,
        restore_cursor: bool = False,
        human_like: bool = True,
        speed_factor: float = 3.0,
        hold_duration: Optional[float] = None,
        stay_clicked: Optional[float] = None,
        **kwargs: Any,
    ) -> bool:
        """Envoie un clic de souris aux coordonnées relatives (x, y) dans la fenêtre."""
        return self._impl.click(
            x,
            y,
            restore_cursor=restore_cursor,
            human_like=human_like,
            speed_factor=speed_factor,
            hold_duration=hold_duration,
            stay_clicked=stay_clicked,
            **kwargs,
        )

    @staticmethod
    def list_windows() -> List[IWindow]:
        """Liste toutes les fenêtres actives."""
        return WindowFactory.list_windows()

    @staticmethod
    def build_tree(filter_active: bool = True) -> IWindow:
        """Construit l'arborescence globale des fenêtres du système."""
        return WindowFactory.build_desktop_tree(filter_active=filter_active)


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
