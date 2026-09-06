import platform
from typing import Optional, List

from .base import IWindow
from .geometry import WindowGeometry


class WindowsWindow(IWindow):
    def _find_hwnd(self) -> Optional[int]:
        if platform.system() != "Windows":
            return None
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        found = []

        def enum_proc(hwnd, lParam):
            if user32.IsWindowVisible(hwnd):
                win_pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(win_pid))

                length = user32.GetWindowTextLengthW(hwnd)
                buff = ctypes.create_unicode_buffer(length + 1)
                if length > 0:
                    user32.GetWindowTextW(hwnd, buff, length + 1)
                win_title = buff.value

                match_id = (self.window_id is not None and str(hwnd) == str(self.window_id))
                match_pid = (self.pid is not None and win_pid.value == self.pid)
                match_title = (bool(self.title) and self.title.lower() in win_title.lower())

                if match_id or match_pid or match_title:
                    self.window_id = str(hwnd)
                    if self.pid is None and win_pid.value:
                        self.pid = win_pid.value
                    self.title = win_title
                    found.append(hwnd)
                    return False
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows(WNDENUMPROC(enum_proc), 0)
        return found[0] if found else None

    def exists(self) -> bool:
        return self._find_hwnd() is not None

    def get_geometry(self, include_decorations: bool = False) -> Optional[WindowGeometry]:
        if platform.system() != "Windows":
            return None
        import ctypes
        from ctypes import wintypes

        hwnd = self._find_hwnd()
        if not hwnd:
            return None

        user32 = ctypes.windll.user32

        if not include_decorations:
            # Récupérer la zone cliente réelle sans barre de titre
            client_rect = wintypes.RECT()
            if user32.GetClientRect(hwnd, ctypes.byref(client_rect)):
                pt = wintypes.POINT(client_rect.left, client_rect.top)
                user32.ClientToScreen(hwnd, ctypes.byref(pt))
                self.geometry = WindowGeometry(
                    left=pt.x,
                    top=pt.y,
                    width=client_rect.right - client_rect.left,
                    height=client_rect.bottom - client_rect.top,
                )
                return self.geometry

        # Avec décorations / bordures
        try:
            dwmapi = ctypes.windll.dwmapi
            rect = wintypes.RECT()
            DWMWA_EXTENDED_FRAME_BOUNDS = 9
            hr = dwmapi.DwmGetWindowAttribute(
                hwnd,
                DWMWA_EXTENDED_FRAME_BOUNDS,
                ctypes.byref(rect),
                ctypes.sizeof(rect),
            )
            if hr == 0:
                self.geometry = WindowGeometry(
                    left=rect.left,
                    top=rect.top,
                    width=rect.right - rect.left,
                    height=rect.bottom - rect.top,
                )
                return self.geometry
        except Exception:
            pass

        rect = wintypes.RECT()
        if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            self.geometry = WindowGeometry(
                left=rect.left,
                top=rect.top,
                width=rect.right - rect.left,
                height=rect.bottom - rect.top,
            )
            return self.geometry
        return None

    def activate(self) -> bool:
        if platform.system() != "Windows":
            return False
        import ctypes

        hwnd = self._find_hwnd()
        if hwnd:
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            return True
        return False

    def get_tree(self) -> "WindowsWindow":
        """Construit récursivement l'arbre des fenêtres enfants via EnumChildWindows."""
        if platform.system() != "Windows":
            return self

        import ctypes
        from ctypes import wintypes

        hwnd = self._find_hwnd()
        if not hwnd:
            return self

        user32 = ctypes.windll.user32

        def enum_children(parent_hwnd, parent_node):
            def child_proc(child_hwnd, lParam):
                child_pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(child_hwnd, ctypes.byref(child_pid))

                length = user32.GetWindowTextLengthW(child_hwnd)
                buff = ctypes.create_unicode_buffer(length + 1)
                if length > 0:
                    user32.GetWindowTextW(child_hwnd, buff, length + 1)

                rect = wintypes.RECT()
                user32.GetWindowRect(child_hwnd, ctypes.byref(rect))
                geom = WindowGeometry(
                    left=rect.left,
                    top=rect.top,
                    width=rect.right - rect.left,
                    height=rect.bottom - rect.top,
                )

                child_node = WindowsWindow(
                    pid=child_pid.value,
                    title=buff.value,
                    window_id=str(child_hwnd),
                    geometry=geom,
                )
                parent_node.add_child(child_node)
                enum_children(child_hwnd, child_node)
                return True

            WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            user32.EnumChildWindows(parent_hwnd, WNDENUMPROC(child_proc), 0)

        enum_children(hwnd, self)
        return self

    @classmethod
    def build_desktop_tree(cls, filter_active: bool = True) -> "WindowsWindow":
        root = cls(title="Bureau Windows")
        for win in cls.list_all():
            win.get_tree()
            root.add_child(win)
        return root

    @classmethod
    def list_all(cls) -> List["WindowsWindow"]:
        if platform.system() != "Windows":
            return []
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        windows = []

        def enum_proc(hwnd, lParam):
            if user32.IsWindowVisible(hwnd):
                win_pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(win_pid))

                length = user32.GetWindowTextLengthW(hwnd)
                buff = ctypes.create_unicode_buffer(length + 1)
                if length > 0:
                    user32.GetWindowTextW(hwnd, buff, length + 1)
                if buff.value:
                    windows.append(cls(pid=win_pid.value, title=buff.value, window_id=str(hwnd)))
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows(WNDENUMPROC(enum_proc), 0)
        return windows
