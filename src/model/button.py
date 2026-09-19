import time
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Any, Union, Tuple
import yaml
import numpy as np
from PIL import Image

from .matcher import ImageMatcher
from .state import parse_threshold


@dataclass
class ButtonCondition:
    """Condition sur une ROI pour un bouton : template(s), seuil et mode couleur."""
    roi_name: str
    template: Union[str, List[str]]
    threshold: float = 0.85
    color: bool = True
    method: str = "exact"


@dataclass
class ButtonMatch:
    """Résultat de détection d'un bouton."""
    name: str
    is_visible: bool
    score: float
    details: Dict[str, float] = field(default_factory=dict)
    position: Tuple[int, int] = (0, 0)
    template_size: Tuple[int, int] = (0, 0)
    roi_name: str = ""
    hold_duration: Optional[float] = None

    @property
    def stay_clicked(self) -> Optional[float]:
        """Alias rétrocompatible pour hold_duration."""
        return self.hold_duration

    def center(self, resolved_rois: Dict[str, Any]) -> Tuple[int, int]:
        """Calcule les coordonnées (x, y) du centre du bouton dans la fenêtre."""
        roi = resolved_rois.get(self.roi_name)
        rx = getattr(roi, "x", 0)
        ry = getattr(roi, "y", 0)
        cx = rx + self.position[0] + (self.template_size[0] // 2)
        cy = ry + self.position[1] + (self.template_size[1] // 2)
        return (cx, cy)

    def click(
        self,
        game_window: Any,
        resolved_rois: Dict[str, Any],
        restore_cursor: bool = False,
        hold_duration: Optional[float] = None,
        stay_clicked: Optional[float] = None,
        **kwargs: Any,
    ) -> bool:
        """Envoie directement un clic au centre du bouton dans la fenêtre."""
        cx, cy = self.center(resolved_rois)
        duration = hold_duration if hold_duration is not None else (stay_clicked if stay_clicked is not None else self.hold_duration)
        return game_window.click(
            cx,
            cy,
            restore_cursor=restore_cursor,
            hold_duration=duration,
            stay_clicked=duration,
            **kwargs,
        )


@dataclass
class ButtonSpec:
    """Spécification d'un bouton déclarée dans buttons.yaml."""
    name: str
    requires: Dict[str, ButtonCondition] = field(default_factory=dict)
    states: List[str] = field(default_factory=list)
    auto: Optional[str] = None           # Clé du paramètre automatique (ex: "auto_help")
    cooldown: float = 2.0                # Temps minimum (s) entre deux clics automatiques
    restore_cursor: bool = True          # Restauration de la position du curseur après le clic
    hold_duration: Optional[float] = None # Durée d'appui prolongé sur le clic (en secondes)
    _last_triggered: float = field(default=0.0, init=False, repr=False)

    @property
    def stay_clicked(self) -> Optional[float]:
        """Alias rétrocompatible pour hold_duration."""
        return self.hold_duration

    def can_trigger(self) -> bool:
        """Indique si le cooldown est écoulé pour une exécution automatique."""
        return (time.time() - self._last_triggered) >= self.cooldown

    def mark_triggered(self) -> None:
        """Enregistre l'horodatage du déclenchement."""
        self._last_triggered = time.time()

    def execute(
        self,
        match: ButtonMatch,
        game_window: Any,
        resolved_rois: Dict[str, Any],
        restore_cursor: Optional[bool] = None,
        hold_duration: Optional[float] = None,
        stay_clicked: Optional[float] = None,
        **kwargs: Any,
    ) -> bool:
        """Exécute le clic automatique si le cooldown le permet (restaure le curseur selon config)."""
        if self.can_trigger():
            rc = self.restore_cursor if restore_cursor is None else restore_cursor
            duration = hold_duration if hold_duration is not None else (stay_clicked if stay_clicked is not None else self.hold_duration)
            success = match.click(
                game_window,
                resolved_rois,
                restore_cursor=rc,
                hold_duration=duration,
                stay_clicked=duration,
                **kwargs,
            )
            if success:
                self.mark_triggered()
            return success
        return False

    def evaluate(
        self,
        crops: Dict[str, Union[Image.Image, np.ndarray]],
        matcher: ImageMatcher,
    ) -> Tuple[bool, float, Dict[str, float], Tuple[int, int], str, Tuple[int, int]]:
        """
        Évalue si ce bouton est visible d'après les crops des ROIs.
        Retourne : (matches, score_moyen, scores_par_roi, position, roi_name, template_size).
        """
        if not self.requires:
            return (False, 0.0, {}, (0, 0), "", (0, 0))

        scores = {}
        primary_roi = ""
        primary_pos = (0, 0)
        primary_size = (0, 0)

        for roi_name, condition in self.requires.items():
            crop = crops.get(roi_name)
            if crop is None:
                return (False, 0.0, scores, (0, 0), "", (0, 0))

            templates = (
                condition.template
                if isinstance(condition.template, list)
                else [condition.template]
            )

            best_score = 0.0
            best_pos = (0, 0)
            best_size = (0, 0)

            for tpl in templates:
                try:
                    score, pos, tpl_size = matcher.match_detailed(
                        crop, tpl, color=condition.color, method=condition.method
                    )
                    if score > best_score:
                        best_score = score
                        best_pos = pos
                        best_size = tpl_size
                    if best_score >= condition.threshold:
                        break
                except FileNotFoundError:
                    continue

            scores[roi_name] = best_score
            if not primary_roi:
                primary_roi = roi_name
                primary_pos = best_pos
                primary_size = best_size

            if best_score < condition.threshold:
                return (False, best_score, scores, (0, 0), "", (0, 0))

        avg_score = float(np.mean(list(scores.values()))) if scores else 1.0
        return (True, avg_score, scores, primary_pos, primary_roi, primary_size)

    def evaluate_multiple(
        self,
        crops: Dict[str, Union[Image.Image, np.ndarray]],
        matcher: "ImageMatcher",
        threshold_override: Optional[float] = None
    ) -> List["ButtonMatch"]:
        """
        Évalue toutes les occurrences de ce bouton dans les crops.
        """
        if not self.requires:
            return []

        all_matches = []
        for roi_name, cond in self.requires.items():
            if roi_name not in crops:
                continue
                
            crop = crops[roi_name]
            if crop is None:
                continue

            templates = (
                cond.template
                if isinstance(cond.template, list)
                else [cond.template]
            )
            if not templates:
                continue
                
            color = cond.color
            method = cond.method
            threshold = cond.threshold
            if threshold_override is not None:
                threshold = threshold_override

            for tpl in templates:
                if not tpl: continue
                # Call matcher.match_detailed_multiple
                try:
                    results = matcher.match_detailed_multiple(crop, tpl, threshold=threshold, color=color, method=method)
                except AttributeError:
                    results = []
    
                for score, pos, size in results:
                    all_matches.append(ButtonMatch(
                        name=self.name,
                        is_visible=True,
                        score=score,
                        details={roi_name: score},
                        position=pos,
                        template_size=size,
                        roi_name=roi_name,
                        hold_duration=self.hold_duration,
                    ))

        # Sort by score descending
        all_matches.sort(key=lambda m: m.score, reverse=True)
        return all_matches


class ButtonManager:
    """Gestionnaire et détecteur de boutons déclarés dans buttons.yaml."""

    def __init__(
        self,
        buttons_yaml: Optional[Union[str, Path]] = None,
        templates_dir: Optional[Union[str, Path]] = None,
        templates_root: Optional[Union[str, Path]] = None,
        lang: str = "en",
        matcher: Optional[ImageMatcher] = None,
    ):
        self.buttons: Dict[str, ButtonSpec] = {}
        self.lang = lang
        self.matcher = matcher or ImageMatcher(
            templates_dir=templates_dir,
            templates_root=templates_root,
            lang=lang,
        )

        if buttons_yaml is not None:
            self.load_yaml(buttons_yaml)

    def get(self, name: str) -> Optional[ButtonSpec]:
        """Récupère la spécification d'un bouton par son nom."""
        return self.buttons.get(name)

    def load_yaml(self, buttons_yaml: Union[str, Path]) -> None:
        path = Path(buttons_yaml)
        if not path.exists():
            return

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        raw_buttons = data.get("buttons", {}) if data else {}
        global_threshold = parse_threshold(
            (data.get("threshold") or data.get("default_threshold")) if data else None,
            default=0.85,
        )
        self.buttons.clear()

        for name, spec in raw_buttons.items():
            if spec is None:
                spec = {}

            # États autorisés (optionnel)
            states_raw = spec.get("states") or spec.get("state")
            if states_raw is None:
                states = []
            elif isinstance(states_raw, list):
                states = [str(s) for s in states_raw]
            else:
                states = [str(states_raw)]

            btn_threshold = parse_threshold(spec.get("threshold"), default=global_threshold)

            # Automatisation déclarative
            auto_feature = spec.get("auto")
            cooldown_raw = spec.get("cooldown", 2.0)
            try:
                cooldown_val = float(str(cooldown_raw).rstrip("s").strip())
            except ValueError:
                cooldown_val = 2.0

            # Conditions requires
            requires = {}
            req_data = spec.get("requires", {}) or {}
            for roi_name, cond in req_data.items():
                if isinstance(cond, str):
                    requires[roi_name] = ButtonCondition(
                        roi_name=roi_name,
                        template=cond,
                        threshold=btn_threshold,
                        color=True,
                    )
                elif isinstance(cond, list):
                    requires[roi_name] = ButtonCondition(
                        roi_name=roi_name,
                        template=[str(t) for t in cond],
                        threshold=btn_threshold,
                        color=True,
                    )
                elif isinstance(cond, dict):
                    t_raw = cond.get("template", "")
                    if isinstance(t_raw, list):
                        t_val = [str(t) for t in t_raw]
                    else:
                        t_val = str(t_raw)
                    requires[roi_name] = ButtonCondition(
                        roi_name=roi_name,
                        template=t_val,
                        threshold=parse_threshold(cond.get("threshold"), default=btn_threshold),
                        color=bool(cond.get("color", True)),
                        method=cond.get("method", "exact"),
                    )

            # Restauration du curseur (supporte save_mouse, restore_cursor, restore_position)
            restore_cursor_raw = spec.get("save_mouse", spec.get("restore_cursor", spec.get("restore_position", True)))
            restore_cursor = bool(restore_cursor_raw)

            # Maintien du clic prolongé (hold_duration ou stay_clicked en secondes, optionnel)
            hold_raw = spec.get("hold_duration", spec.get("stay_clicked"))
            hold_val: Optional[float] = None
            if hold_raw is not None:
                try:
                    hold_val = float(str(hold_raw).rstrip("s").strip())
                except ValueError:
                    hold_val = None

            self.buttons[name] = ButtonSpec(
                name=name,
                requires=requires,
                states=states,
                auto=str(auto_feature).strip() if auto_feature else None,
                cooldown=cooldown_val,
                restore_cursor=restore_cursor,
                hold_duration=hold_val,
            )

        max_workers = min(8, os.cpu_count() or 4)
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ButtonWorker")

    def close(self) -> None:
        """Libère le pool de threads."""
        if hasattr(self, "_pool"):
            self._pool.shutdown(wait=False)

    def __del__(self) -> None:
        self.close()

    def detect_visible_buttons(
        self,
        crops: Dict[str, Union[Image.Image, np.ndarray]],
        current_state: Optional[str] = None,
        spatial_disambiguation_radius: int = 40,
        target_names: Optional[Any] = None,
    ) -> Dict[str, ButtonMatch]:
        """
        Analyse l'ensemble des boutons définis (ou un sous-ensemble ciblé) et retourne ceux qui sont visibles.
        Évaluation multithreadée NOGIL sur tous les cœurs CPU disponibles.
        Applique un arbitrage spatial (Non-Maximum Suppression) : si deux boutons
        se superposent au même endroit dans la même ROI (ex: alliance_button vs
        alliance_notification_button), seul celui avec le meilleur score est conservé.
        """
        if target_names:
            target_set = set(target_names)
            items_to_check = [(n, self.buttons[n]) for n in target_set if n in self.buttons]
        else:
            items_to_check = list(self.buttons.items())

        # Filtrer par état si spécifié
        filtered_items = []
        for name, button in items_to_check:
            if current_state and button.states:
                if current_state not in button.states:
                    continue
            filtered_items.append((name, button))

        def _eval_button(item: Tuple[str, ButtonSpec]) -> Optional[ButtonMatch]:
            name, button = item
            matches, score, details, pos, roi_name, tpl_size = button.evaluate(crops, self.matcher)
            if matches:
                return ButtonMatch(
                    name=name,
                    is_visible=True,
                    score=score,
                    details=details,
                    position=pos,
                    template_size=tpl_size,
                    roi_name=roi_name,
                    hold_duration=button.hold_duration,
                )
            return None

        # Évaluation concurrente multithreadée NOGIL
        if len(filtered_items) > 1:
            eval_results = list(self._pool.map(_eval_button, filtered_items))
            candidates = [r for r in eval_results if r is not None]
        elif filtered_items:
            res = _eval_button(filtered_items[0])
            candidates = [res] if res is not None else []
        else:
            candidates = []

        # Solution 1 : Arbitrage spatial par score de similarité décroissant
        candidates.sort(key=lambda b: b.score, reverse=True)
        accepted: Dict[str, ButtonMatch] = {}

        for cand in candidates:
            conflict = False
            for acc in accepted.values():
                if cand.roi_name == acc.roi_name and cand.roi_name != "":
                    dx = abs(cand.position[0] - acc.position[0])
                    dy = abs(cand.position[1] - acc.position[1])
                    if dx <= spatial_disambiguation_radius and dy <= spatial_disambiguation_radius:
                        # Conflit spatial : les deux variantes occupent le même emplacement
                        conflict = True
                        break
            if not conflict:
                accepted[cand.name] = cand

        return accepted

    def detect_all_visible_buttons(
        self,
        crops: Dict[str, Union[Image.Image, np.ndarray]],
        current_state: Optional[str] = None,
        target_names: Optional[Any] = None,
    ) -> Dict[str, List[ButtonMatch]]:
        """
        Retourne TOUTES les occurrences visibles pour chaque bouton ciblé.
        """
        if target_names:
            target_set = set(target_names)
            items_to_check = [(n, self.buttons[n]) for n in target_set if n in self.buttons]
        else:
            items_to_check = list(self.buttons.items())

        filtered_items = []
        for name, button in items_to_check:
            if current_state and button.states:
                if current_state not in button.states:
                    continue
            filtered_items.append((name, button))

        def _eval_multi(item: Tuple[str, "ButtonSpec"]) -> Tuple[str, List[ButtonMatch]]:
            name, button = item
            return name, button.evaluate_multiple(crops, self.matcher)

        results: Dict[str, List[ButtonMatch]] = {}
        if len(filtered_items) > 1:
            eval_results = list(self._pool.map(_eval_multi, filtered_items))
            for name, matches in eval_results:
                if matches:
                    results[name] = matches
        elif filtered_items:
            name, matches = _eval_multi(filtered_items[0])
            if matches:
                results[name] = matches

        return results

        for cand in candidates:
            conflict = False
            for acc in accepted.values():
                if cand.roi_name == acc.roi_name and cand.roi_name != "":
                    dx = abs(cand.position[0] - acc.position[0])
                    dy = abs(cand.position[1] - acc.position[1])
                    if dx <= spatial_disambiguation_radius and dy <= spatial_disambiguation_radius:
                        # Conflit spatial : les deux variantes occupent le même emplacement
                        conflict = True
                        break
            if not conflict:
                accepted[cand.name] = cand

        return accepted
