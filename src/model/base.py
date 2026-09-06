from abc import ABC, abstractmethod
from typing import Optional, Any, List

from .geometry import WindowGeometry

try:
    import mss
    import mss.tools
    MSSContext = getattr(mss, "MSS", getattr(mss, "mss", None))
except ImportError:
    mss = None
    MSSContext = None


class IWindow(ABC):
    """
    Interface abstraite représentant une fenêtre ou un nœud dans l'arborescence des fenêtres.
    Chaque nœud possède un identifiant (window_id / handle), un PID, un nom (title),
    sa géométrie, son parent et ses fenêtres enfants.
    """

    def __init__(
        self,
        pid: Optional[int | str] = None,
        title: str = "",
        window_id: Optional[str] = None,
        geometry: Optional[WindowGeometry] = None,
        parent: Optional["IWindow"] = None,
    ):
        # Tolérance si un titre est passé en premier argument positionnel (ex: Window("Titre"))
        if isinstance(pid, str) and not title:
            self.title = pid
            self.pid = None
        else:
            self.pid = int(pid) if pid is not None else None
            self.title = title

        self.window_id: Optional[str] = window_id
        self.geometry: Optional[WindowGeometry] = geometry
        self.parent: Optional["IWindow"] = parent
        self.children: List["IWindow"] = []

    def __repr__(self) -> str:
        id_str = f" id={self.window_id}" if self.window_id else ""
        return f"<{self.__class__.__name__}{id_str} pid={self.pid} title={self.title!r}>"

    def add_child(self, child: "IWindow") -> None:
        """Ajoute une fenêtre enfant et propage le PID du parent s'il est manquant."""
        child.parent = self
        if child.pid is None and self.pid is not None:
            child.pid = self.pid
        self.children.append(child)

    def tree_str(self, depth: int = 0) -> str:
        """
        Génère une représentation arborescente textuelle lisible (avec PID, ID, nom, géométrie).
        """
        prefix = "  " * depth + ("└── " if depth > 0 else "")
        pid_s = f"[PID: {self.pid}] " if self.pid is not None else "[PID: -] "
        id_s = f"({self.window_id}) " if self.window_id else ""
        name_s = f'"{self.title}"' if self.title else "(sans nom)"
        geom_s = (
            f" [{self.geometry.width}x{self.geometry.height} @ ({self.geometry.left}, {self.geometry.top})]"
            if self.geometry
            else ""
        )
        lines = [f"{prefix}{pid_s}{id_s}{name_s}{geom_s}"]
        for child in self.children:
            lines.append(child.tree_str(depth + 1))
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Sérialise le nœud et toute son arborescence récursive en dictionnaire."""
        return {
            "window_id": self.window_id,
            "pid": self.pid,
            "title": self.title,
            "geometry": self.geometry.to_dict() if self.geometry else None,
            "children": [child.to_dict() for child in self.children],
        }

    def find_all(
        self, title: Optional[str] = None, pid: Optional[int] = None
    ) -> List["IWindow"]:
        """Recherche récursive dans l'arborescence par titre partiel et/ou par PID."""
        results = []
        match_pid = (pid is not None and self.pid == pid)
        match_title = (bool(title) and bool(self.title) and title.lower() in self.title.lower())
        if match_pid or match_title:
            results.append(self)
        for child in self.children:
            results.extend(child.find_all(title=title, pid=pid))
        return results

    @abstractmethod
    def exists(self) -> bool:
        """Vérifie si la fenêtre est actuellement ouverte."""
        pass

    @abstractmethod
    def get_geometry(self, include_decorations: bool = False) -> Optional[WindowGeometry]:
        """
        Récupère dynamiquement la géométrie courante (position et taille).
        Si include_decorations=False (défaut), renvoie la zone de contenu réelle (client area).
        Si include_decorations=True, inclut la barre de titre et les bordures du cadre.
        """
        pass

    @abstractmethod
    def activate(self) -> bool:
        """Donne le focus à la fenêtre (la passe au premier plan)."""
        pass

    @abstractmethod
    def get_tree(self) -> "IWindow":
        """Construit et retourne l'arborescence des sous-fenêtres (enfants) de cette fenêtre."""
        pass

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
        Envoie un clic de souris aux coordonnées relatives (x, y) dans la fenêtre.
        Si human_like=True, utilise un déplacement courbé réaliste (human x3).
        Si restore_cursor=True, sauvegarde la position originale du curseur et la restaure après le clic.
        Si hold_duration (ou stay_clicked) est défini, maintient le clic enfoncé pendant la durée indiquée (s).
        Retourne True en cas de succès, False sinon.
        """
        return False

    def capture(
        self, output_path: Optional[str] = None, include_decorations: bool = False
    ) -> Optional[Any]:
        """
        Prend une capture d'écran de la zone actuelle de la fenêtre via mss.
        Si include_decorations=False (défaut), capture exactement l'intérieur du jeu/de l'application
        sans décalage de barre de titre.
        Si include_decorations=True, capture le cadre complet avec sa bordure et barre de titre.
        Gère le dépassement d'écran éventuel (clamping) pour éviter les erreurs X11/OS.
        """
        geom = self.get_geometry(include_decorations=include_decorations)
        if not geom:
            return None

        if mss is None or MSSContext is None:
            raise ImportError("Le package 'mss' est requis pour effectuer des captures d'écran.")

        if not hasattr(self, "_sct") or self._sct is None:
            self._sct = MSSContext()

        sct = self._sct
        screen = sct.monitors[0]
        left = max(screen["left"], geom.left)
        top = max(screen["top"], geom.top)
        right = min(screen["left"] + screen["width"], geom.left + geom.width)
        bottom = min(screen["top"] + screen["height"], geom.top + geom.height)

        width = max(0, right - left)
        height = max(0, bottom - top)

        if width <= 0 or height <= 0:
            return None

        sct_img = sct.grab({"left": left, "top": top, "width": width, "height": height})
        if output_path:
            mss.tools.to_png(sct_img.rgb, sct_img.size, output=output_path)
        return sct_img

    def __del__(self) -> None:
        if getattr(self, "_sct", None) is not None:
            try:
                self._sct.close()
            except Exception:
                pass
