from dataclasses import dataclass, field
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional, List, Dict, Any, Union, Tuple
import yaml
from PIL import Image
import numpy as np

from .matcher import ImageMatcher
from .roi import ResolvedROI


@dataclass
class StateCondition:
    """Condition sur une ROI : template(s) attendu(s), seuil de similarité et mode couleur."""
    roi_name: str
    template: Union[str, List[str]]
    threshold: float = 0.90
    color: bool = True
    method: str = "exact"


@dataclass
class StateSpec:
    """Définition d'un état du jeu."""
    name: str
    priority: int = 0
    parents: List[str] = field(default_factory=list)
    requires: Dict[str, StateCondition] = field(default_factory=dict)

    def evaluate(
        self,
        crops: Dict[str, Union[Image.Image, np.ndarray]],
        matcher: ImageMatcher,
    ) -> Tuple[bool, float, Dict[str, float]]:
        """
        Évalue si cet état correspond aux images découpées des ROIs.
        Retourne : (matches, score_moyen, scores_par_roi).
        """
        if not self.requires:
            # État sans condition (ex: unknown)
            return (True, 1.0, {})

        scores = {}
        for roi_name, condition in self.requires.items():
            crop = crops.get(roi_name)
            if crop is None:
                return (False, 0.0, scores)

            templates = (
                condition.template
                if isinstance(condition.template, list)
                else [condition.template]
            )

            best_score = 0.0
            for tpl in templates:
                try:
                    score = matcher.compute_similarity(
                        crop, tpl, color=condition.color, method=condition.method
                    )
                    if score > best_score:
                        best_score = score
                    # Court-circuit immédiat si un des templates dépasse le seuil
                    if best_score >= condition.threshold:
                        break
                except FileNotFoundError:
                    continue

            scores[roi_name] = best_score
            if best_score < condition.threshold:
                return (False, best_score, scores)

        avg_score = float(np.mean(list(scores.values()))) if scores else 1.0
        return (True, avg_score, scores)


def parse_threshold(val: Any, default: float = 0.90) -> float:
    """Parse un seuil flottant (ex: 0.7, 0.85) ou pourcentage (ex: 70, '70%')."""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val) / 100.0 if val > 1.0 else float(val)
    val_str = str(val).strip().rstrip("%")
    try:
        num = float(val_str)
        return num / 100.0 if num > 1.0 else num
    except ValueError:
        return default


class StateManager:
    """Gestionnaire des états du jeu et de la machine à états."""

    def __init__(
        self,
        states_yaml: Optional[Union[str, Path]] = None,
        templates_dir: Optional[Union[str, Path]] = None,
        templates_root: Optional[Union[str, Path]] = None,
        lang: str = "en",
        matcher: Optional[ImageMatcher] = None,
    ):
        self.states: Dict[str, StateSpec] = {}
        self.current_state: str = "unknown"
        self.lang = lang
        self.matcher = matcher or ImageMatcher(
            templates_dir=templates_dir,
            templates_root=templates_root,
            lang=lang,
        )

        if states_yaml is not None:
            self.load_yaml(states_yaml)

    def load_yaml(self, states_yaml: Union[str, Path]) -> None:
        path = Path(states_yaml)
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        raw_states = data.get("states", {}) if data else {}
        global_threshold = parse_threshold(
            (data.get("threshold") or data.get("default_threshold")) if data else None,
            default=0.90,
        )
        self.states.clear()

        for name, spec in raw_states.items():
            if spec is None:
                spec = {}

            priority = int(spec.get("priority", 0))
            state_threshold = parse_threshold(spec.get("threshold"), default=global_threshold)

            # Parents
            parents_raw = spec.get("parent")
            if parents_raw is None:
                parents = []
            elif isinstance(parents_raw, list):
                parents = [str(p) for p in parents_raw]
            else:
                parents = [str(parents_raw)]

            # Requires (Option 1)
            requires = {}
            req_data = spec.get("requires", {}) or {}
            for roi_name, cond in req_data.items():
                if isinstance(cond, str):
                    requires[roi_name] = StateCondition(
                        roi_name=roi_name,
                        template=cond,
                        threshold=state_threshold,
                        color=True,
                    )
                elif isinstance(cond, list):
                    requires[roi_name] = StateCondition(
                        roi_name=roi_name,
                        template=[str(t) for t in cond],
                        threshold=state_threshold,
                        color=True,
                    )
                elif isinstance(cond, dict):
                    t_raw = cond.get("template", "")
                    if isinstance(t_raw, list):
                        t_val = [str(t) for t in t_raw]
                    else:
                        t_val = str(t_raw)
                    requires[roi_name] = StateCondition(
                        roi_name=roi_name,
                        template=t_val,
                        threshold=parse_threshold(cond.get("threshold"), default=state_threshold),
                        color=bool(cond.get("color", True)),
                        method=cond.get("method", "exact"),
                    )

            self.states[name] = StateSpec(
                name=name,
                priority=priority,
                parents=parents,
                requires=requires,
            )

        # Indexation par palier de priorité décroissant pour le multithreading NOGIL
        self._prio_groups: Dict[int, List[StateSpec]] = {}
        for s in self.states.values():
            if s.name != "unknown" and s.requires:
                self._prio_groups.setdefault(s.priority, []).append(s)

        max_workers = min(8, os.cpu_count() or 4)
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="StateWorker")

    def close(self) -> None:
        """Libère le pool de threads."""
        if hasattr(self, "_pool"):
            self._pool.shutdown(wait=False)

    def __del__(self) -> None:
        self.close()

    def resolve_state(
        self,
        crops: Dict[str, Union[Image.Image, np.ndarray]],
        enforce_parent: bool = True,
    ) -> Tuple[str, float, Dict[str, Any]]:
        """
        Détermine l'état actif le plus pertinent à partir des images des ROIs.
        Sélectionne l'état valide ayant la plus haute priorité et le meilleur score de similarité.
        Multithreadé par palier de priorité (NOGIL).
        """
        cur_name = self.current_state
        cur_spec = self.states.get(cur_name) if cur_name != "unknown" else None

        def _eval_spec(spec: StateSpec) -> Tuple[StateSpec, bool, float, Dict[str, Any]]:
            m, sc, det = spec.evaluate(crops, self.matcher)
            return (spec, m, sc, det)

        # 1. Fast Path : Continuité temporelle uniquement si l'état actuel est au palier maximum
        max_prio = max(self._prio_groups.keys()) if self._prio_groups else 1
        if cur_spec and cur_spec.priority == max_prio and cur_spec.requires:
            m, sc, det = cur_spec.evaluate(crops, self.matcher)
            if m:
                return (cur_name, sc, det)

        # Détermination des états valides si on force la continuité (State Tree Pruning)
        valid_names = None
        if enforce_parent and cur_name != "unknown":
            valid_names = {cur_name}
            if cur_spec:
                valid_names.update(cur_spec.parents)
            valid_names.update(s.name for s in self.states.values() if cur_name in s.parents)

        # 2. Évaluation multithreadée par palier de priorité décroissante (3 -> 2 -> 1)
        # Les modales et sous-modales priment toujours rigoureusement sur les écrans racine.
        for prio in sorted(self._prio_groups.keys(), reverse=True):
            tier_states = self._prio_groups[prio]
            
            if valid_names is not None:
                tier_states = [s for s in tier_states if s.name in valid_names]
                
            if not tier_states:
                continue

            # Évaluation concurrente multithreadée sur tous les cœurs CPU pour le palier courant
            if len(tier_states) > 1:
                results = list(self._pool.map(_eval_spec, tier_states))
            else:
                results = [_eval_spec(tier_states[0])]

            matches = [r for r in results if r[1]]
            if matches:
                # Le palier courant est le plus haut : toute correspondance valide prime sur les paliers inférieurs !
                matches.sort(key=lambda r: r[2], reverse=True)
                best_spec, _, best_score, best_details = matches[0]
                self.current_state = best_spec.name
                return (best_spec.name, best_score, best_details)

        self.current_state = "unknown"
        return ("unknown", 0.0, {})
