from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Union, Any
import yaml


@dataclass
class SequenceStep:
    """Étape individuelle d'une séquence."""

    type: str
    value: str
    sleep: Optional[float] = None
    kwargs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SequenceSpec:
    """Spécification d'une séquence composée d'étapes."""

    id: str
    label: str
    steps: List[SequenceStep] = field(default_factory=list)
    visible: bool = True
    variant: str = "primary"
    optional: bool = False


class SequenceManager:
    """Gestionnaire des séquences déclarées dans sequences.yaml."""

    def __init__(self, sequences_yaml: Optional[Union[str, Path]] = None):
        self.sequences: Dict[str, SequenceSpec] = {}
        if sequences_yaml:
            self.load_yaml(sequences_yaml)

    def load_yaml(self, sequences_yaml: Union[str, Path]) -> None:
        path = Path(sequences_yaml)
        if not path.is_file():
            raise FileNotFoundError(f"Fichier sequences YAML introuvable : {path}")

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        sequences_data = data.get("sequences", {})
        self.sequences.clear()

        for seq_id, spec in sequences_data.items():
            if not isinstance(spec, dict):
                continue
            label = spec.get("label", str(seq_id).replace("_", " ").title())
            visible = bool(spec.get("visible", False))
            variant = spec.get("variant", "primary")
            optional = bool(spec.get("optional", False))

            steps_raw = spec.get("sequences", spec.get("steps", []))
            steps: List[SequenceStep] = []
            for item in steps_raw:
                if isinstance(item, dict):
                    stype = str(item.get("type", "action"))
                    raw_val = item.get("value", "")
                    if isinstance(raw_val, (list, tuple, set)):
                        val = [str(x) for x in raw_val]
                    else:
                        val = str(raw_val) if raw_val is not None else ""
                    sleep_val = item.get("sleep")
                    if sleep_val is not None:
                        try:
                            sleep_val = float(sleep_val)
                        except (ValueError, TypeError):
                            sleep_val = None
                    extra = {k: v for k, v in item.items() if k not in ("type", "value", "sleep")}
                    steps.append(SequenceStep(type=stype, value=val, sleep=sleep_val, kwargs=extra))

            self.sequences[str(seq_id)] = SequenceSpec(
                id=str(seq_id),
                label=label,
                steps=steps,
                visible=visible,
                variant=variant,
                optional=optional,
            )

    def get(self, sequence_id: str) -> Optional[SequenceSpec]:
        """Retourne la séquence par son identifiant."""
        return self.sequences.get(sequence_id)

    def get_visible_sequences(self) -> List[SequenceSpec]:
        """Retourne la liste des séquences configurées pour être affichées."""
        return [seq for seq in self.sequences.values() if seq.visible]
