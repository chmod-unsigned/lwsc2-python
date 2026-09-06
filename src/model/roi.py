from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Any, Union, Tuple
import yaml
import numpy as np


def parse_coord(val: Union[str, int, float, None]) -> Optional[Union[int, str]]:
    """Parse une coordonnée ou dimension : entier, '135px', '-100px', 'center', 'middle'."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return int(val)
    s = str(val).strip().rstrip(";").strip().lower()
    if "center" in s or "middle" in s:
        return s
    if s.endswith("px"):
        s = s[:-2].strip()
    try:
        return int(s)
    except ValueError:
        return s


@dataclass
class ResolvedROI:
    """Région d'intérêt avec coordonnées absolues résolues en pixels."""
    name: str
    x: int
    y: int
    width: int
    height: int
    states: List[str] = field(default_factory=list)

    @property
    def left(self) -> int:
        return self.x

    @property
    def top(self) -> int:
        return self.y

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def bbox(self) -> Tuple[int, int, int, int]:
        """Retourne (left, top, right, bottom)."""
        return (self.left, self.top, self.right, self.bottom)

    def crop_numpy(self, img: np.ndarray) -> np.ndarray:
        """Découpe la ROI depuis un tableau NumPy (image HxWxC ou HxW)."""
        return img[self.top:self.bottom, self.left:self.right]

    def crop_pillow(self, pil_img: Any) -> Any:
        """Découpe la ROI depuis une image PIL.Image."""
        return pil_img.crop(self.bbox)

    def crop_mss(self, sct_img: Any) -> np.ndarray:
        """Découpe la ROI directement depuis un ScreenShot mss en retournant un tableau NumPy BGRA."""
        arr = np.frombuffer(sct_img.raw, dtype=np.uint8).reshape((sct_img.height, sct_img.width, 4))
        return self.crop_numpy(arr)


@dataclass
class ROISpec:
    """Définition brute d'une ROI (lue depuis le fichier YAML)."""
    name: str
    x: Optional[Union[int, str]] = None
    y: Optional[Union[int, str]] = None
    width: Optional[Union[int, str]] = None
    height: Optional[Union[int, str]] = None
    align: Optional[str] = None
    anchor: Optional[str] = None
    states: List[str] = field(default_factory=list)

    def resolve(self, window_width: int, window_height: int) -> ResolvedROI:
        """
        Résout les dimensions et coordonnées finales selon la taille de la fenêtre (W, H).
        Gère les valeurs négatives relatives aux bords, le centrage ('center', 'middle'),
        ainsi que les attributs explicites align/anchor.
        """
        raw_x = parse_coord(self.x)
        raw_y = parse_coord(self.y)
        raw_w = parse_coord(self.width)
        raw_h = parse_coord(self.height)

        # Prise en compte de align / anchor si x ou y ne sont pas spécifiés
        alignment = str(self.align or self.anchor or "").lower()
        if raw_x is None and ("center" in alignment or "horizontal" in alignment or "middle" in alignment or "hcenter" in alignment):
            raw_x = "center"
        if raw_y is None and ("vertical" in alignment or "middle" in alignment or "vcenter" in alignment):
            raw_y = "center"

        def is_center(v: Any) -> bool:
            return isinstance(v, str) and ("center" in v.lower() or "middle" in v.lower())

        def parse_center_offset(v: str) -> int:
            clean = (
                v.lower()
                .replace("center", "")
                .replace("middle", "")
                .replace("px", "")
                .replace(" ", "")
            )
            if not clean:
                return 0
            try:
                return int(clean)
            except ValueError:
                return 0

        # 1. Résolution de HEIGHT et Y
        if raw_h is None or raw_h == "full":
            res_h = window_height
        elif isinstance(raw_h, str) and str(raw_h).endswith("%"):
            res_h = int(window_height * float(str(raw_h)[:-1]) / 100.0)
        elif isinstance(raw_h, int) and raw_h < 0:
            res_h = abs(raw_h)
        elif isinstance(raw_h, int):
            res_h = raw_h
        else:
            res_h = window_height

        if is_center(raw_y):
            offset = parse_center_offset(str(raw_y))
            res_y = (window_height - res_h) // 2 + offset
        elif raw_y is None:
            if isinstance(raw_h, int) and raw_h < 0:
                res_y = window_height - res_h
            else:
                res_y = 0
        elif isinstance(raw_y, int) and raw_y < 0:
            res_y = window_height + raw_y
            if isinstance(raw_h, int) and raw_h < 0:
                end_y = window_height + raw_h
                res_h = max(0, end_y - res_y)
        else:
            res_y = int(raw_y)
            if isinstance(raw_h, int) and raw_h < 0:
                end_y = window_height + raw_h
                res_h = max(0, end_y - res_y)

        # 2. Résolution de WIDTH et X
        if raw_w is None or raw_w == "full":
            res_w = window_width
        elif isinstance(raw_w, str) and str(raw_w).endswith("%"):
            res_w = int(window_width * float(str(raw_w)[:-1]) / 100.0)
        elif isinstance(raw_w, int) and raw_w < 0:
            res_w = abs(raw_w)
        elif isinstance(raw_w, int):
            res_w = raw_w
        else:
            res_w = window_width

        if is_center(raw_x):
            offset = parse_center_offset(str(raw_x))
            res_x = (window_width - res_w) // 2 + offset
        elif raw_x is None:
            if isinstance(raw_w, int) and raw_w < 0:
                res_x = window_width - res_w
            else:
                res_x = 0
        elif isinstance(raw_x, int) and raw_x < 0:
            res_x = window_width + raw_x
            if isinstance(raw_w, int) and raw_w < 0:
                end_x = window_width + raw_w
                res_w = max(0, end_x - res_x)
        else:
            res_x = int(raw_x)
            if isinstance(raw_w, int) and raw_w < 0:
                end_x = window_width + raw_w
                res_w = max(0, end_x - res_x)

        # Clamping dans les limites de l'image
        res_x = max(0, min(window_width, res_x))
        res_y = max(0, min(window_height, res_y))
        res_w = max(0, min(window_width - res_x, res_w))
        res_h = max(0, min(window_height - res_y, res_h))

        return ResolvedROI(
            name=self.name,
            x=res_x,
            y=res_y,
            width=res_w,
            height=res_h,
            states=list(self.states),
        )


class ROIRegistry:
    """Gestionnaire et chargeur des ROIs définies dans rois.yaml."""

    def __init__(self, yaml_path: Optional[Union[str, Path]] = None):
        self.rois: Dict[str, ROISpec] = {}
        if yaml_path is not None:
            self.load_yaml(yaml_path)

    def load_yaml(self, yaml_path: Union[str, Path]) -> None:
        path = Path(yaml_path)
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        raw_rois = data.get("rois", {}) if data else {}
        for name, spec in raw_rois.items():
            self.rois[name] = ROISpec(
                name=name,
                x=parse_coord(spec.get("x")),
                y=parse_coord(spec.get("y")),
                width=parse_coord(spec.get("width")),
                height=parse_coord(spec.get("height") or spec.get("heigth")),
                align=spec.get("align"),
                anchor=spec.get("anchor"),
                states=spec.get("states", []),
            )

    def get(self, name: str) -> Optional[ROISpec]:
        return self.rois.get(name)

    def resolve_all(self, window_width: int, window_height: int) -> Dict[str, ResolvedROI]:
        """Résout toutes les ROIs pour une dimension d'écran donnée."""
        return {
            name: spec.resolve(window_width, window_height)
            for name, spec in self.rois.items()
        }

    def for_state(self, state_name: str) -> List[ROISpec]:
        """Retourne toutes les ROIs associées à un état donné."""
        return [r for r in self.rois.values() if state_name in r.states]
