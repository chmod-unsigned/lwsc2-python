import platform
import subprocess
from typing import Optional, List

from .base import IWindow
from .geometry import WindowGeometry


class MacWindow(IWindow):
    def exists(self) -> bool:
        return self.get_geometry() is not None

    def get_geometry(self, include_decorations: bool = False) -> Optional[WindowGeometry]:
        if platform.system() != "Darwin":
            return None

        if self.pid is not None:
            cond = f"unix id is {self.pid}"
        elif self.title:
            cond = f'name contains "{self.title}"'
        else:
            return None

        script = f'''
        tell application "System Events"
            set matchingProcesses to (every process whose visible is true and {cond})
            if (count of matchingProcesses) > 0 then
                set proc to item 1 of matchingProcesses
                set win to front window of proc
                set winPos to position of win
                set winSize to size of win
                set pId to unix id of proc
                set pName to name of proc
                return (item 1 of winPos as text) & "," & (item 2 of winPos as text) & "," & (item 1 of winSize as text) & "," & (item 2 of winSize as text) & "," & (pId as text) & "," & pName
            end if
        end tell
        '''
        try:
            output = subprocess.check_output(
                ["osascript", "-e", script], text=True, stderr=subprocess.DEVNULL
            ).strip()
            if output:
                parts = output.split(",")
                left, top, width, height = map(int, parts[:4])
                if len(parts) >= 6:
                    if self.pid is None and parts[4].isdigit():
                        self.pid = int(parts[4])
                    self.title = parts[5]
                self.geometry = WindowGeometry(left=left, top=top, width=width, height=height)
                return self.geometry
        except (subprocess.SubprocessError, ValueError, FileNotFoundError):
            pass
        return None

    def activate(self) -> bool:
        if platform.system() != "Darwin":
            return False

        if self.pid is not None:
            cond = f"unix id is {self.pid}"
        elif self.title:
            cond = f'name contains "{self.title}"'
        else:
            return False

        script = f'''
        tell application "System Events"
            set matchingProcesses to (every process whose visible is true and {cond})
            if (count of matchingProcesses) > 0 then
                set frontmost of (item 1 of matchingProcesses) to true
                return true
            end if
        end tell
        '''
        try:
            subprocess.run(["osascript", "-e", script], check=True, stderr=subprocess.DEVNULL)
            return True
        except (subprocess.SubprocessError, FileNotFoundError):
            return False

    def get_tree(self) -> "MacWindow":
        """Sur macOS, liste les fenêtres enfants / éléments UI du processus."""
        if platform.system() != "Darwin" or self.pid is None:
            return self

        script = f'''
        tell application "System Events"
            set matchingProcesses to (every process whose visible is true and unix id is {self.pid})
            if (count of matchingProcesses) > 0 then
                set proc to item 1 of matchingProcesses
                set winList to every window of proc
                set res to ""
                repeat with w in winList
                    set res to res & (name of w as text) & "\n"
                end repeat
                return res
            end if
        end tell
        '''
        try:
            output = subprocess.check_output(
                ["osascript", "-e", script], text=True, stderr=subprocess.DEVNULL
            ).strip()
            for line in output.splitlines():
                if line.strip():
                    self.add_child(MacWindow(pid=self.pid, title=line.strip()))
        except (subprocess.SubprocessError, FileNotFoundError):
            pass
        return self

    @classmethod
    def build_desktop_tree(cls, filter_active: bool = True) -> "MacWindow":
        root = cls(title="Bureau macOS")
        for win in cls.list_all():
            win.get_tree()
            root.add_child(win)
        return root

    @classmethod
    def list_all(cls) -> List["MacWindow"]:
        if platform.system() != "Darwin":
            return []
        script = """
        tell application "System Events"
            set procList to every process whose visible is true
            set res to ""
            repeat with p in procList
                set res to res & (unix id of p as text) & "\t" & (name of p as text) & "\n"
            end repeat
            return res
        end tell
        """
        windows = []
        try:
            output = subprocess.check_output(
                ["osascript", "-e", script], text=True, stderr=subprocess.DEVNULL
            ).strip()
            for line in output.splitlines():
                if "\t" in line:
                    pid_str, name = line.split("\t", 1)
                    windows.append(cls(pid=int(pid_str) if pid_str.isdigit() else None, title=name))
        except (subprocess.SubprocessError, FileNotFoundError):
            pass
        return windows
