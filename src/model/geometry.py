from dataclasses import dataclass


@dataclass
class WindowGeometry:
    left: int
    top: int
    width: int
    height: int

    def to_dict(self) -> dict[str, int]:
        """Format de dictionnaire attendu par mss (top, left, width, height)."""
        return {
            "top": self.top,
            "left": self.left,
            "width": self.width,
            "height": self.height,
        }

    def __getitem__(self, item: str) -> int:
        return getattr(self, item)
