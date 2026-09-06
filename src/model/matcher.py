from pathlib import Path
from typing import Union, Optional, Tuple, Dict
import numpy as np
from PIL import Image


class ImageMatcher:
    """
    Moteur de comparaison d'images et templates en mémoire utilisant NumPy et Pillow.
    Optimisé pour Python 3.13 free-threaded.
    """

    def __init__(
        self,
        templates_dir: Optional[Union[str, Path]] = None,
        templates_root: Optional[Union[str, Path]] = None,
        lang: str = "en",
    ):
        self.lang = lang
        self.templates_root = Path(templates_root) if templates_root else Path("templates")
        self.templates_dir = (
            Path(templates_dir) if templates_dir else (self.templates_root / self.lang)
        )
        self._cache_rgb: Dict[str, np.ndarray] = {}
        self._cache_gray: Dict[str, np.ndarray] = {}
        self._cache_sub4: Dict[str, np.ndarray] = {}
        self._cache_sub2: Dict[str, np.ndarray] = {}
        self._path_cache: Dict[str, Path] = {}
        self._transient_gray_cache: Dict[int, np.ndarray] = {}
        self._transient_rgb_cache: Dict[int, np.ndarray] = {}
        # Pour compatibilité descendante
        self._cache = self._cache_rgb

    def clear_transient_cache(self) -> None:
        """Vide le cache éphémère des découpes de frame."""
        self._transient_gray_cache.clear()
        self._transient_rgb_cache.clear()

    def resolve_template_path(self, img_path: Union[str, Path]) -> Path:
        """Résout le chemin d'un template selon l'ordre de priorité linguistique."""
        str_key = str(img_path)
        if str_key in self._path_cache:
            return self._path_cache[str_key]

        path = Path(img_path)
        if not path.is_absolute():
            # 1. Recherche dans le dossier de la langue active (ex: templates/fr/ ou templates/en/)
            if self.templates_dir and (self.templates_dir / path).exists():
                path = self.templates_dir / path
            # 2. Recherche directe dans templates_root / lang
            elif (self.templates_root / self.lang / path).exists():
                path = self.templates_root / self.lang / path
            # 3. Fallback vers la langue par défaut 'en' si manquante dans la langue courante
            elif (self.templates_root / "en" / path).exists():
                path = self.templates_root / "en" / path
            # 4. Fallback vers templates_root directement
            elif (self.templates_root / path).exists():
                path = self.templates_root / path
            elif self.templates_dir:
                path = self.templates_dir / path

        if not path.exists():
            raise FileNotFoundError(f"Template introuvable : {path}")

        resolved = path.resolve()
        self._path_cache[str_key] = resolved
        self._path_cache[resolved.name] = resolved
        return resolved

    def preload_templates(self) -> int:
        """
        Précharge toutes les images du dossier templates en RAM (RGB, Niveaux de gris et sous-échantillons).
        Élimine les I/O disque et prépare les pyramides NumPy float32.
        Retourne le nombre de templates uniques chargés.
        """
        if not self.templates_root.exists():
            return 0

        # Dossiers à scanner (priorité : templates_root, puis fallback 'en', puis langue active)
        search_dirs = [self.templates_root]
        fallback_dir = self.templates_root / "en"
        if fallback_dir.exists() and fallback_dir not in search_dirs:
            search_dirs.append(fallback_dir)
        if self.templates_dir and self.templates_dir.exists() and self.templates_dir not in search_dirs:
            search_dirs.append(self.templates_dir)

        weights = np.array([0.299, 0.587, 0.114], dtype=np.float32)
        loaded_count = 0
        seen_resolved = set()

        for d in search_dirs:
            for file_path in d.glob("*.png"):
                try:
                    resolved = file_path.resolve()
                    resolved_str = str(resolved)
                    if resolved_str not in seen_resolved:
                        seen_resolved.add(resolved_str)
                        with Image.open(resolved) as loaded:
                            arr_rgb = np.array(loaded.convert("RGB"), dtype=np.float32)
                        arr_gray = np.dot(arr_rgb[..., :3], weights)

                        # Enregistrement sous la clé absolue
                        self._cache_rgb[resolved_str] = arr_rgb
                        self._cache_gray[resolved_str] = arr_gray
                        self._cache_sub4[resolved_str] = arr_gray[::4, ::4]
                        self._cache_sub2[resolved_str] = arr_gray[::2, ::2]

                        loaded_count += 1

                    # Mappages d'accès rapide O(1)
                    arr_rgb = self._cache_rgb[resolved_str]
                    arr_gray = self._cache_gray[resolved_str]

                    self._cache_rgb[file_path.name] = arr_rgb
                    self._cache_gray[file_path.name] = arr_gray
                    self._cache_sub4[file_path.name] = self._cache_sub4[resolved_str]
                    self._cache_sub2[file_path.name] = self._cache_sub2[resolved_str]

                    self._path_cache[file_path.name] = resolved
                    self._path_cache[str(file_path)] = resolved
                except Exception:
                    continue

        return loaded_count

    def to_rgb_array(self, img: Union[Image.Image, np.ndarray, Path, str]) -> np.ndarray:
        """Convertit une image PIL, un chemin ou un tableau NumPy en float32 RGB (H, W, 3)."""
        if isinstance(img, (str, Path)):
            str_key = str(img)
            if str_key in self._cache_rgb:
                return self._cache_rgb[str_key]

            path = self.resolve_template_path(img)
            cache_key = str(path)
            if cache_key in self._cache_rgb:
                arr = self._cache_rgb[cache_key]
                self._cache_rgb[str_key] = arr
                return arr

            with Image.open(path) as loaded:
                arr = np.array(loaded.convert("RGB"), dtype=np.float32)
            self._cache_rgb[cache_key] = arr
            self._cache_rgb[str_key] = arr
            return arr

        if isinstance(img, Image.Image):
            return np.array(img.convert("RGB"), dtype=np.float32)

        if isinstance(img, np.ndarray):
            if img.ndim == 2:  # Niveaux de gris
                return np.stack([img] * 3, axis=-1).astype(np.float32)
            elif img.shape[-1] == 4:  # RGBA / BGRA
                return img[..., :3].astype(np.float32)
            return img.astype(np.float32)

        raise TypeError(f"Type d'image non supporté : {type(img)}")

    def to_gray_array(self, img: Union[Image.Image, np.ndarray, Path, str]) -> np.ndarray:
        """Convertit une image PIL, un chemin ou un tableau NumPy en float32 niveaux de gris (H, W)."""
        weights = np.array([0.299, 0.587, 0.114], dtype=np.float32)

        if isinstance(img, (str, Path)):
            str_key = str(img)
            if str_key in self._cache_gray:
                return self._cache_gray[str_key]

            path = self.resolve_template_path(img)
            cache_key = str(path)
            if cache_key in self._cache_gray:
                arr_gray = self._cache_gray[cache_key]
                self._cache_gray[str_key] = arr_gray
                return arr_gray

            with Image.open(path) as loaded:
                arr_rgb = np.array(loaded.convert("RGB"), dtype=np.float32)
            arr_gray = np.dot(arr_rgb[..., :3], weights)
            self._cache_rgb[cache_key] = arr_rgb
            self._cache_gray[cache_key] = arr_gray
            self._cache_rgb[str_key] = arr_rgb
            self._cache_gray[str_key] = arr_gray
            return arr_gray

        if isinstance(img, Image.Image):
            return np.array(img.convert("L"), dtype=np.float32)

        if isinstance(img, np.ndarray):
            if img.ndim == 2:
                return img.astype(np.float32)
            elif img.shape[-1] >= 3:
                return np.dot(img[..., :3].astype(np.float32), weights)
            return img.astype(np.float32)

        raise TypeError(f"Type d'image non supporté : {type(img)}")

    def compute_similarity(
        self,
        crop: Union[Image.Image, np.ndarray, Path, str],
        template: Union[Image.Image, np.ndarray, Path, str],
        color: bool = True,
    ) -> float:
        """Calcule le score de similarité (de 0.0 à 1.0) entre une ROI et un template."""
        return self.match_detailed(crop, template, color=color)[0]

    def match_detailed(
        self,
        crop: Union[Image.Image, np.ndarray, Path, str],
        template: Union[Image.Image, np.ndarray, Path, str],
        color: bool = True,
    ) -> Tuple[float, Tuple[int, int], Tuple[int, int]]:
        """
        Calcule le score de similarité, la position (x, y) et la taille (w, h) du template.
        Retourne : (score, (match_x, match_y), (template_w, template_h)).
        """
        # Préparation des matrices RGB et/ou Grayscale
        if color:
            crop_rgb = self.to_rgb_array(crop)
            tpl_rgb = self.to_rgb_array(template)
            crop_gray = self.to_gray_array(crop)
            tpl_gray = self.to_gray_array(template)
        else:
            crop_rgb = None
            tpl_rgb = None
            crop_gray = self.to_gray_array(crop)
            tpl_gray = self.to_gray_array(template)

        ch, cw = crop_gray.shape[:2]
        th, tw = tpl_gray.shape[:2]

        if ch == 0 or cw == 0 or th == 0 or tw == 0:
            return (0.0, (0, 0), (tw, th))

        # Cas 1 : Dimensions identiques (comparaison directe ultra-rapide)
        if ch == th and cw == tw:
            if color and crop_rgb is not None and tpl_rgb is not None:
                diff = np.abs(crop_rgb - tpl_rgb)
            else:
                diff = np.abs(crop_gray - tpl_gray)
            score = float(max(0.0, 1.0 - (np.mean(diff) / 255.0)))
            return (score, (0, 0), (tw, th))

        # Cas 2 : Le template est contenu dans la ROI -> coarse-to-fine vectorisé en niveaux de gris
        if th <= ch and tw <= cw:
            scale = 4 if (ch > 200 or cw > 200) else (2 if (ch > 60 or cw > 60) else 1)

            if scale == 1:
                windows = np.lib.stride_tricks.sliding_window_view(crop_gray, (th, tw))
                diffs = np.mean(np.abs(windows - tpl_gray), axis=(-2, -1))
                sy, sx = np.unravel_index(np.argmin(diffs), diffs.shape)
                best_x, best_y = int(sx), int(sy)
            else:
                # 1. Étape grossière sous-échantillonnée (vectorisée 2D)
                c_sub = crop_gray[::scale, ::scale]
                t_sub = tpl_gray[::scale, ::scale]
                sth, stw = t_sub.shape[:2]

                w = np.lib.stride_tricks.sliding_window_view(c_sub, (sth, stw))
                diffs = np.mean(np.abs(w - t_sub), axis=(-2, -1))
                flat_idx = np.argsort(diffs.ravel())
                top_diff = diffs.ravel()[flat_idx[0]]
                coarse_score = float(max(0.0, 1.0 - (top_diff / 255.0)))

                # Rejet rapide immédiat : si la similarité grossière est trop faible (< 55%),
                # aucune recherche fine ne pourra atteindre un seuil de match standard (0.80+)
                if coarse_score < 0.55:
                    bsy, bsx = np.unravel_index(flat_idx[0], diffs.shape)
                    return (coarse_score, (int(bsx) * scale, int(bsy) * scale), (tw, th))

                # 2. Étape fine au pixel près autour des meilleurs candidats (top-3)
                radius = scale * 2 + 2
                best_overall_score = -1.0
                best_x, best_y = 0, 0

                # On teste les 3 meilleurs candidats grossiers
                candidates = flat_idx[:min(3, len(flat_idx))]
                for c_idx in candidates:
                    bsy, bsx = np.unravel_index(c_idx, diffs.shape)
                    bx = int(bsx) * scale
                    by = int(bsy) * scale

                    min_y = max(0, by - radius)
                    max_y = min(ch - th, by + radius)
                    min_x = max(0, bx - radius)
                    max_x = min(cw - tw, bx + radius)

                    sub_crop = crop_gray[min_y : max_y + th, min_x : max_x + tw]
                    fw = np.lib.stride_tricks.sliding_window_view(sub_crop, (th, tw))
                    fdiffs = np.mean(np.abs(fw - tpl_gray), axis=(-2, -1))
                    fsy, fsx = np.unravel_index(np.argmin(fdiffs), fdiffs.shape)
                    cand_x = min_x + int(fsx)
                    cand_y = min_y + int(fsy)

                    cand_x = max(0, min(cw - tw, cand_x))
                    cand_y = max(0, min(ch - th, cand_y))

                    if color and crop_rgb is not None and tpl_rgb is not None:
                        matched_patch = crop_rgb[cand_y : cand_y + th, cand_x : cand_x + tw]
                        final_diff = np.abs(matched_patch - tpl_rgb)
                    else:
                        matched_patch = crop_gray[cand_y : cand_y + th, cand_x : cand_x + tw]
                        final_diff = np.abs(matched_patch - tpl_gray)

                    cand_score = float(max(0.0, 1.0 - (np.mean(final_diff) / 255.0)))
                    if cand_score > best_overall_score:
                        best_overall_score = cand_score
                        best_x, best_y = cand_x, cand_y

                return (best_overall_score, (best_x, best_y), (tw, th))

        # Cas 3 : Dimensions différentes (le template dépasse du crop -> redimensionnement)
        if color and crop_rgb is not None and tpl_rgb is not None:
            tpl_target = tpl_rgb
            crop_target = crop_rgb
        else:
            tpl_target = tpl_gray
            crop_target = crop_gray

        tpl_pil = Image.fromarray(np.clip(tpl_target, 0, 255).astype(np.uint8))
        resized_tpl = tpl_pil.resize((cw, ch), Image.Resampling.BILINEAR)
        resized_arr = np.array(resized_tpl, dtype=np.float32)

        # Garantir la compatibilité des formes
        if crop_target.ndim == 2 and resized_arr.ndim == 3:
            resized_arr = resized_arr[..., 0]
        elif crop_target.ndim == 3 and resized_arr.ndim == 2:
            resized_arr = np.stack([resized_arr] * 3, axis=-1)

        diff = np.abs(crop_target - resized_arr)
        score = float(max(0.0, 1.0 - (np.mean(diff) / 255.0)))
        return (score, (0, 0), (tw, th))
