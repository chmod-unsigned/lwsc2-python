import subprocess
import re
import time
from typing import Optional, List, Dict, Tuple, Any

from .base import IWindow
from .geometry import WindowGeometry


class LinuxWindow(IWindow):
    @staticmethod
    def _get_wmctrl_pid_map() -> Dict[int, Tuple[Optional[int], str]]:
        """Construit une table de correspondance window_id (int) -> (PID, titre)."""
        pid_map: Dict[int, Tuple[Optional[int], str]] = {}
        try:
            output = subprocess.check_output(
                ["wmctrl", "-lp"], text=True, stderr=subprocess.DEVNULL
            )
            for line in output.splitlines():
                parts = line.split(maxsplit=4)
                if len(parts) >= 3:
                    try:
                        wid_int = int(parts[0], 16)
                        pid = int(parts[2]) if parts[2].isdigit() else None
                        title = parts[4] if len(parts) >= 5 else ""
                        pid_map[wid_int] = (pid, title)
                    except ValueError:
                        continue
        except (subprocess.SubprocessError, FileNotFoundError):
            pass
        return pid_map

    def get_frame_extents(self) -> Tuple[int, int, int, int]:
        """
        Retourne (left, right, top, bottom) des bordures et barre de titre via _NET_FRAME_EXTENTS.
        Permet de corriger les décalages de coordonnées des gestionnaires de fenêtres X11.
        """
        if not self.window_id:
            return (0, 0, 0, 0)
        try:
            out = subprocess.check_output(
                ["xprop", "-id", self.window_id, "_NET_FRAME_EXTENTS"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            # Format attendu : _NET_FRAME_EXTENTS(CARDINAL) = left, right, top, bottom
            m = re.search(r"=\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)", out)
            if m:
                return (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)))
        except (subprocess.SubprocessError, FileNotFoundError):
            pass
        return (0, 0, 0, 0)

    def _find_wmctrl_line(self) -> Optional[list[str]]:
        try:
            output = subprocess.check_output(
                ["wmctrl", "-lpG"], text=True, stderr=subprocess.DEVNULL
            )
            for line in output.splitlines():
                parts = line.split(maxsplit=8)
                if len(parts) >= 9:
                    win_pid = int(parts[2]) if parts[2].isdigit() else None
                    win_title = parts[8]
                    wid = parts[0]

                    match_id = (self.window_id is not None and int(wid, 16) == int(self.window_id, 16))
                    match_pid = (self.pid is not None and win_pid == self.pid)
                    match_title = (bool(self.title) and self.title.lower() in win_title.lower())

                    if match_id or match_pid or match_title:
                        self.window_id = wid
                        if win_pid and self.pid is None:
                            self.pid = win_pid
                        self.title = win_title
                        try:
                            self.desktop = int(parts[1]) if parts[1].lstrip("-").isdigit() else None
                        except (ValueError, IndexError):
                            self.desktop = None
                        return parts
        except (subprocess.SubprocessError, FileNotFoundError):
            pass
        return None

    def exists(self) -> bool:
        return self._find_wmctrl_line() is not None

    def get_geometry(self, include_decorations: bool = False) -> Optional[WindowGeometry]:
        """
        Résout les coordonnées exactes à l'écran.
        xwininfo fournit les vraies coordonnées absolues X/Y réelles de la zone cliente.
        Contrairement à wmctrl qui décale le haut en ajoutant indûment la barre de titre.
        """
        self.exists()  # S'assure que self.window_id est résolu

        # 1. Utilisation de xwininfo (précision absolue sur X11)
        if self.window_id:
            try:
                out = subprocess.check_output(
                    ["xwininfo", "-id", self.window_id],
                    text=True,
                    stderr=subprocess.DEVNULL,
                )
                x_m = re.search(r"Absolute upper-left X:\s+(-?\d+)", out)
                y_m = re.search(r"Absolute upper-left Y:\s+(-?\d+)", out)
                w_m = re.search(r"Width:\s+(\d+)", out)
                h_m = re.search(r"Height:\s+(\d+)", out)

                if x_m and y_m and w_m and h_m:
                    left = int(x_m.group(1))
                    top = int(y_m.group(1))
                    width = int(w_m.group(1))
                    height = int(h_m.group(1))

                    if include_decorations:
                        ext_l, ext_r, ext_t, ext_b = self.get_frame_extents()
                        left -= ext_l
                        top -= ext_t
                        width += (ext_l + ext_r)
                        height += (ext_t + ext_b)

                    self.geometry = WindowGeometry(left=left, top=top, width=width, height=height)
                    return self.geometry
            except (subprocess.SubprocessError, FileNotFoundError):
                pass

        # 2. Fallback avec wmctrl (en corrigeant l'offset de barre de titre)
        parts = self._find_wmctrl_line()
        if parts:
            try:
                raw_x = int(parts[3])
                raw_y = int(parts[4])
                raw_w = int(parts[5])
                raw_h = int(parts[6])

                ext_l, ext_r, ext_t, ext_b = self.get_frame_extents()
                # wmctrl ajoute la taille de la barre de titre (ext_t) au Y client
                client_y = raw_y - ext_t

                if include_decorations:
                    self.geometry = WindowGeometry(
                        left=raw_x - ext_l,
                        top=client_y - ext_t,
                        width=raw_w + ext_l + ext_r,
                        height=raw_h + ext_t + ext_b,
                    )
                else:
                    self.geometry = WindowGeometry(left=raw_x, top=client_y, width=raw_w, height=raw_h)
                return self.geometry
            except (ValueError, IndexError):
                pass

        # 3. Fallback avec xdotool
        try:
            cmd = ["xdotool", "search"]
            if self.window_id:
                wid = self.window_id
            else:
                if self.pid is not None:
                    cmd.extend(["--pid", str(self.pid)])
                elif self.title:
                    cmd.extend(["--name", self.title])
                else:
                    return None
                wid_output = subprocess.check_output(
                    cmd, text=True, stderr=subprocess.DEVNULL
                ).strip().splitlines()
                wid = wid_output[-1] if wid_output else None

            if wid:
                geom_output = subprocess.check_output(
                    ["xdotool", "getwindowgeometry", wid],
                    text=True,
                    stderr=subprocess.DEVNULL,
                )
                pos_match = re.search(r"Position:\s*(\d+),(\d+)", geom_output)
                geo_match = re.search(r"Geometry:\s*(\d+)x(\d+)", geom_output)
                if pos_match and geo_match:
                    left = int(pos_match.group(1))
                    top = int(pos_match.group(2))
                    width = int(geo_match.group(1))
                    height = int(geo_match.group(2))
                    ext_l, ext_r, ext_t, ext_b = self.get_frame_extents()
                    top -= ext_t  # Correction offset
                    if include_decorations:
                        left -= ext_l
                        top -= ext_t
                        width += (ext_l + ext_r)
                        height += (ext_t + ext_b)
                    self.geometry = WindowGeometry(left=left, top=top, width=width, height=height)
                    return self.geometry
        except (subprocess.SubprocessError, FileNotFoundError):
            pass

        return None

    def activate(self) -> bool:
        self.exists()
        if hasattr(self, "desktop") and self.desktop is not None and self.desktop >= 0:
            try:
                subprocess.run(["wmctrl", "-s", str(self.desktop)], check=False, stderr=subprocess.DEVNULL)
            except (subprocess.SubprocessError, FileNotFoundError):
                pass

        if self.window_id:
            try:
                subprocess.run(["wmctrl", "-i", "-a", str(self.window_id)], check=False, stderr=subprocess.DEVNULL)
                subprocess.run(["xdotool", "windowactivate", "--sync", str(self.window_id)], check=False, stderr=subprocess.DEVNULL)
                return True
            except (subprocess.SubprocessError, FileNotFoundError):
                pass

        if self.title:
            try:
                subprocess.run(["wmctrl", "-a", self.title], check=True, stderr=subprocess.DEVNULL)
                return True
            except (subprocess.SubprocessError, FileNotFoundError):
                pass

        return False

    def get_tree(self) -> "LinuxWindow":
        """Construit l'arborescence des sous-fenêtres de cette fenêtre spécifique."""
        self.exists()  # Résout window_id et PID si besoin
        if not self.window_id:
            return self

        try:
            output = subprocess.check_output(
                ["xwininfo", "-tree", "-id", self.window_id],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            tree = self._parse_xwininfo_tree(output, default_root=self)
            return tree
        except (subprocess.SubprocessError, FileNotFoundError):
            return self

    @classmethod
    def _parse_xwininfo_tree(
        cls,
        output_text: str,
        default_root: Optional["LinuxWindow"] = None,
        pid_map: Optional[Dict[int, Tuple[Optional[int], str]]] = None,
    ) -> "LinuxWindow":
        """Parse la sortie de xwininfo -tree pour assembler l'arborescence."""
        if pid_map is None:
            pid_map = cls._get_wmctrl_pid_map()

        pattern_header = re.compile(
            r'^xwininfo: Window id: (0x[0-9a-fA-F]+)\s*(?:\"([^\"]*)\"|\(has no name\))?'
        )
        pattern_child = re.compile(
            r'^(\s*)(0x[0-9a-fA-F]+)\s+(\"[^\"]*\"|\(has no name\)):\s*.*?(\d+)x(\d+)\+(-?\d+)\+(-?\d+)\s+\+(-?\d+)\+(-?\d+)'
        )

        root: Optional[LinuxWindow] = default_root
        if default_root is not None:
            default_root.children = []
            stack: List[Tuple[LinuxWindow, int]] = [(default_root, -1)]
        else:
            stack = []

        for line in output_text.splitlines():
            if root is None:
                hm = pattern_header.match(line)
                if hm:
                    wid = hm.group(1)
                    title = hm.group(2) or ""
                    wid_int = int(wid, 16)
                    pid, mapped_title = pid_map.get(wid_int, (None, ""))
                    if not title and mapped_title:
                        title = mapped_title
                    root = cls(pid=pid, title=title, window_id=wid)
                    stack = [(root, -1)]
                    continue

            cm = pattern_child.search(line)
            if cm and (root is not None):
                indent_str, wid, name_raw, w, h, rx, ry, ax, ay = cm.groups()
                indent = len(indent_str)
                title = name_raw.strip('"') if name_raw != "(has no name)" else ""
                wid_int = int(wid, 16)
                pid, mapped_title = pid_map.get(wid_int, (None, ""))
                if not title and mapped_title:
                    title = mapped_title

                geom = WindowGeometry(left=int(ax), top=int(ay), width=int(w), height=int(h))
                node = cls(pid=pid, title=title, window_id=wid, geometry=geom)

                while len(stack) > 1 and stack[-1][1] >= indent:
                    stack.pop()

                if stack:
                    parent = stack[-1][0]
                    parent.add_child(node)
                stack.append((node, indent))

        if root is None:
            root = cls(title="Racine")
        return root

    @classmethod
    def build_desktop_tree(cls, filter_active: bool = True) -> "LinuxWindow":
        """
        Construit l'arborescence complète des fenêtres du bureau via xwininfo -root -tree.
        Si filter_active=True, élague les fenêtres internes anonymes sans PID ni titre.
        """
        pid_map = cls._get_wmctrl_pid_map()
        try:
            output = subprocess.check_output(
                ["xwininfo", "-root", "-tree"], text=True, stderr=subprocess.DEVNULL
            )
            tree = cls._parse_xwininfo_tree(output, pid_map=pid_map)

            if filter_active:
                def is_meaningful(n: IWindow) -> bool:
                    return bool(n.title or n.pid is not None or any(is_meaningful(c) for c in n.children))

                def filter_node(n: IWindow) -> None:
                    n.children = [c for c in n.children if is_meaningful(c)]
                    for c in n.children:
                        filter_node(c)

                filter_node(tree)

            return tree
        except (subprocess.SubprocessError, FileNotFoundError):
            return cls(title="Bureau")

    @classmethod
    def list_all(cls) -> List["LinuxWindow"]:
        windows = []
        try:
            output = subprocess.check_output(
                ["wmctrl", "-lpG"], text=True, stderr=subprocess.DEVNULL
            )
            for line in output.splitlines():
                parts = line.split(maxsplit=8)
                if len(parts) >= 9:
                    wid = parts[0]
                    win_pid = int(parts[2]) if parts[2].isdigit() else None
                    geom = WindowGeometry(
                        left=int(parts[3]),
                        top=int(parts[4]),
                        width=int(parts[5]),
                        height=int(parts[6]),
                    )
                    win_title = parts[8]
                    windows.append(cls(pid=win_pid, title=win_title, window_id=wid, geometry=geom))
        except (subprocess.SubprocessError, FileNotFoundError):
            pass
        return windows

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
        """
        Envoie un clic de souris aux coordonnées relatives (x, y) de la zone cliente du jeu.
        Si human_like=True, déplace le curseur avec une trajectoire courbée réaliste et une vitesse 'human x3'.
        Si restore_cursor=True, sauvegarde la position initiale de la souris et la restaure après le clic.
        Si hold_duration (ou stay_clicked) est défini, maintient le clic enfoncé pendant la durée indiquée (en secondes).
        """
        self.exists()
        if not self.window_id:
            return False

        duration = hold_duration if hold_duration is not None else stay_clicked

        try:
            if hasattr(self, "desktop") and self.desktop is not None and self.desktop >= 0:
                try:
                    subprocess.run(["wmctrl", "-s", str(self.desktop)], check=False, stderr=subprocess.DEVNULL)
                except Exception:
                    pass

            # Donner le focus à la fenêtre du jeu
            subprocess.run(
                ["xdotool", "windowactivate", "--sync", str(self.window_id)],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            geom = self.get_geometry(include_decorations=False)
            if geom:
                abs_x = geom.left + int(x)
                abs_y = geom.top + int(y)
            else:
                abs_x = int(x)
                abs_y = int(y)

            if human_like:
                from .mouse import human_click
                return human_click(
                    abs_x,
                    abs_y,
                    restore_cursor=restore_cursor,
                    speed_factor=speed_factor,
                    hold_duration=duration,
                )
            else:
                # Mode instantané brut via xdotool
                sleep_val = f"{duration:.3f}" if (duration is not None and duration > 0) else "0.02"
                cmd = ["xdotool", "mousemove", str(abs_x), str(abs_y), "mousedown", "1", "sleep", sleep_val, "mouseup", "1"]
                subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
        except (subprocess.SubprocessError, FileNotFoundError, Exception):
            return False
