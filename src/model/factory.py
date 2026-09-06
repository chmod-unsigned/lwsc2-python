from abc import ABC, abstractmethod
import platform
from typing import Optional, List

from .base import IWindow
from .linux import LinuxWindow
from .windows import WindowsWindow
from .mac import MacWindow


class WindowFactory(ABC):
    @abstractmethod
    def create_window(self, pid: Optional[int] = None, title: str = "") -> IWindow:
        pass

    @abstractmethod
    def find_windows(self) -> List[IWindow]:
        pass

    @abstractmethod
    def build_tree(self, filter_active: bool = True) -> IWindow:
        pass

    @classmethod
    def get_factory_for_current_os(cls) -> "WindowFactory":
        system = platform.system()
        if system == "Linux":
            return LinuxWindowFactory()
        elif system == "Windows":
            return WindowsWindowFactory()
        elif system == "Darwin":
            return MacWindowFactory()
        raise NotImplementedError(f"Plateforme non supportée : {system}")

    @staticmethod
    def create(pid: Optional[int] = None, title: str = "") -> IWindow:
        """Instancie directement la fenêtre adaptée à la plateforme active."""
        if isinstance(pid, str) and not title:
            title = pid
            pid = None
        system = platform.system()
        if system == "Linux":
            return LinuxWindow(pid=pid, title=title)
        elif system == "Windows":
            return WindowsWindow(pid=pid, title=title)
        elif system == "Darwin":
            return MacWindow(pid=pid, title=title)
        raise NotImplementedError(f"Système d'exploitation non supporté : {system}")

    @classmethod
    def list_windows(cls) -> List[IWindow]:
        """Liste toutes les fenêtres ouvertes sur l'OS actif avec leur PID et leur titre."""
        return cls.get_factory_for_current_os().find_windows()

    @classmethod
    def build_desktop_tree(cls, filter_active: bool = True) -> IWindow:
        """Construit l'arborescence complète des fenêtres du système."""
        return cls.get_factory_for_current_os().build_tree(filter_active=filter_active)


class LinuxWindowFactory(WindowFactory):
    def create_window(self, pid: Optional[int] = None, title: str = "") -> IWindow:
        return LinuxWindow(pid=pid, title=title)

    def find_windows(self) -> List[IWindow]:
        return LinuxWindow.list_all()

    def build_tree(self, filter_active: bool = True) -> IWindow:
        return LinuxWindow.build_desktop_tree(filter_active=filter_active)


class WindowsWindowFactory(WindowFactory):
    def create_window(self, pid: Optional[int] = None, title: str = "") -> IWindow:
        return WindowsWindow(pid=pid, title=title)

    def find_windows(self) -> List[IWindow]:
        return WindowsWindow.list_all()

    def build_tree(self, filter_active: bool = True) -> IWindow:
        return WindowsWindow.build_desktop_tree(filter_active=filter_active)


class MacWindowFactory(WindowFactory):
    def create_window(self, pid: Optional[int] = None, title: str = "") -> IWindow:
        return MacWindow(pid=pid, title=title)

    def find_windows(self) -> List[IWindow]:
        return MacWindow.list_all()

    def build_tree(self, filter_active: bool = True) -> IWindow:
        return MacWindow.build_desktop_tree(filter_active=filter_active)
