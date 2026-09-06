from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Union
import yaml


@dataclass
class ActionSpec:
    """Spécification d'une action utilisateur liée à des états et des boutons."""

    id: str
    label: str
    states: List[str] = field(default_factory=list)
    buttons: List[str] = field(default_factory=list)
    variant: str = "primary"
    hold_duration: Optional[float] = None

    @property
    def stay_clicked(self) -> Optional[float]:
        """Alias rétrocompatible pour hold_duration."""
        return self.hold_duration

    def is_available_in(self, state: Optional[str]) -> bool:
        """Indique si cette action est disponible pour l'état de jeu donné."""
        if not self.states:
            return True
        if not state:
            return False
        return state.lower() in [s.lower() for s in self.states]


class ActionManager:
    """Gestionnaire des actions déclarées dans actions.yaml."""

    def __init__(self, actions_yaml: Optional[Union[str, Path]] = None):
        self.actions: Dict[str, ActionSpec] = {}
        if actions_yaml:
            self.load_yaml(actions_yaml)

    def load_yaml(self, actions_yaml: Union[str, Path]) -> None:
        path = Path(actions_yaml)
        if not path.is_file():
            raise FileNotFoundError(f"Fichier actions YAML introuvable : {path}")

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        actions_data = data.get("actions", {})
        self.actions.clear()

        for action_id, spec in actions_data.items():
            label = spec.get("label", action_id.replace("_", " ").title())
            states_raw = spec.get("states", [])
            if isinstance(states_raw, str):
                states = [states_raw]
            elif isinstance(states_raw, list):
                states = [str(s) for s in states_raw]
            else:
                states = []

            buttons_raw = spec.get("buttons", [])
            if isinstance(buttons_raw, str):
                buttons = [buttons_raw]
            elif isinstance(buttons_raw, list):
                buttons = [str(b) for b in buttons_raw]
            else:
                buttons = []

            variant = spec.get("variant", "primary")

            # Maintien du clic prolongé (hold_duration ou stay_clicked en secondes)
            hold_raw = spec.get("hold_duration", spec.get("stay_clicked"))
            hold_val: Optional[float] = None
            if hold_raw is not None:
                try:
                    hold_val = float(str(hold_raw).rstrip("s").strip())
                except ValueError:
                    hold_val = None

            self.actions[str(action_id)] = ActionSpec(
                id=str(action_id),
                label=label,
                states=states,
                buttons=buttons,
                variant=variant,
                hold_duration=hold_val,
            )

    def get(self, action_id: str) -> Optional[ActionSpec]:
        """Retourne l'action par son identifiant."""
        return self.actions.get(action_id)

    def get_actions_for_state(self, state: Optional[str]) -> List[ActionSpec]:
        """Retourne la liste des actions valides pour l'état donné dans l'ordre de définition."""
        return [act for act in self.actions.values() if act.is_available_in(state)]

    def get_actions(
        self,
        state: Optional[str],
        visible_buttons: Optional[Union[set, list, dict]] = None,
    ) -> List[ActionSpec]:
        """
        Retourne la liste des actions disponibles selon l'état actuel ET la visibilité réelle de leurs boutons.
        Si visible_buttons est fourni, une action nécessitant des boutons n'apparaît que si au moins un bouton est visible.
        """
        actions = self.get_actions_for_state(state)
        if visible_buttons is not None:
            v_set = set(visible_buttons.keys()) if isinstance(visible_buttons, dict) else set(visible_buttons)
            actions = [
                act for act in actions
                if not act.buttons or any(b in v_set for b in act.buttons)
            ]
        return actions

    def all_actions(self) -> List[ActionSpec]:
        """Retourne toutes les actions déclarées."""
        return list(self.actions.values())
