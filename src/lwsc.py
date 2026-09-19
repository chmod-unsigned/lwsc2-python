import time
import threading
import random
import pyautogui
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional, Any, Union, Set
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Button, Log, Label, TabbedContent, TabPane, Checkbox
from textual.containers import Horizontal, Vertical, ItemGrid
from textual import work
from PIL import Image

from model.window import Window
from model.roi import ROIRegistry
from model.matcher import ImageMatcher
from model.state import StateManager
from model.button import ButtonManager
from model.action import ActionManager
from model.sequence import SequenceManager, SequenceSpec, SequenceStep
from model.mouse import human_move


class Lwsc(App):
    CSS = """
    #state_banner {
        width: 100%;
        text-align: center;
        text-style: bold;
        padding: 1;
        background: $boost;
        border: solid $accent;
        margin-top: 1;
    }
    TabbedContent {
        height: 1fr;
        margin-top: 1;
    }
    #actions_container, #sequences_container, #params_container {
        padding: 1;
        height: 1fr;
    }
    #bottom_actions {
        height: auto;
        width: 100%;
        margin-top: 1;
    }
    #bottom_actions Button {
        min-width: 18;
    }
    #params_container Checkbox {
        margin-bottom: 1;
    }
    .section_title {
        text-style: bold;
        margin-bottom: 1;
    }
    .info_muted {
        color: $text-muted;
        padding: 1;
        text-style: italic;
    }
    #action_buttons, #sequence_buttons {
        height: auto;
        width: 100%;
        margin-bottom: 1;
        grid-gutter: 1 1;
    }
    #action_buttons Button, #sequence_buttons Button {
        width: 100%;
    }
    #buttons { height: auto; width: 100%; margin-top: 1; margin-bottom: 1; }
    #buttons Button { margin-right: 1; }
    Log { border: solid green; height: 1fr; }
    """

    lang: str = "en"
    poll_interval: float = 0.05  # Fréquence d'analyse : jusqu'à 20 fois par seconde (instantané)

    def __init__(self):
        super().__init__()
        self._stop_tracking = threading.Event()
        self.tracking_enabled = True
        self.settings: Dict[str, bool] = {
            "auto_help": False,
            "auto_loot": False,
        }
        self.last_resolved_rois: Dict[str, Any] = {}
        self.last_visible_buttons: Dict[str, Any] = {}

        project_root = Path(__file__).resolve().parent.parent
        config_dir = project_root / "config"

        self.action_mgr = ActionManager(config_dir / "actions.yaml")
        self.sequence_mgr = SequenceManager(config_dir / "sequences.yaml")
        self.displayed_actions: List[str] = []
        self._action_in_progress: bool = False
        self.current_state: Optional[str] = None

        # Préchargement de l'ensemble des templates d'images en RAM (matrices NumPy float32)
        self.matcher = ImageMatcher(
            templates_root=project_root / "templates",
            lang=self.lang,
        )
        self.preloaded_count = self.matcher.preload_templates()

        # Partage des instances préchargées
        self.roi_reg = ROIRegistry(config_dir / "rois.yaml")
        self.state_mgr = StateManager(
            config_dir / "states.yaml",
            templates_root=project_root / "templates",
            lang=self.lang,
            matcher=self.matcher,
        )
        self.button_mgr = ButtonManager(
            config_dir / "buttons.yaml",
            templates_root=project_root / "templates",
            lang=self.lang,
            matcher=self.matcher,
        )

        # Injection dynamique des états depuis les actions vers les boutons
        # Cela permet d'éviter la redondance dans buttons.yaml
        for action in self.action_mgr.actions.values():
            for btn_name in action.buttons:
                btn = self.button_mgr.get(btn_name)
                if btn:
                    for s in action.states:
                        if s not in btn.states:
                            btn.states.append(s)

        self.game_window = Window("Last War")
        self.mouse_speed_factor: float = 3.0  # Vitesse réaliste 'human x3'

    @property
    def auto_help_enabled(self) -> bool:
        return self.settings.get("auto_help", False)

    @auto_help_enabled.setter
    def auto_help_enabled(self, value: bool) -> None:
        self.settings["auto_help"] = value

    @property
    def auto_loot_enabled(self) -> bool:
        return self.settings.get("auto_loot", False)

    @auto_loot_enabled.setter
    def auto_loot_enabled(self, value: bool) -> None:
        self.settings["auto_loot"] = value

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("🎮 État du jeu : [bold cyan]INITIALISATION...[/bold cyan]", id="state_banner")
        with TabbedContent(initial="tab_actions"):
            with TabPane("Actions", id="tab_actions"):
                with Vertical(id="actions_container"):
                    yield Label("⚡ Actions disponibles :", classes="section_title")
                    with ItemGrid(id="action_buttons", min_column_width=18):
                        initial_actions = [act for act in self.action_mgr.get_actions_for_state("headquarter") if act.id != "return"]
                        self.displayed_actions = [act.id for act in initial_actions]
                        for act in initial_actions:
                            yield Button(act.label, id=f"act_{act.id}", variant=act.variant)
                    with Horizontal(id="bottom_actions"):
                        pass
            with TabPane("Sequences", id="tab_sequences"):
                with Vertical(id="sequences_container"):
                    yield Label("📜 Séquences disponibles :", classes="section_title")
                    with ItemGrid(id="sequence_buttons", min_column_width=24):
                        visible_seqs = self.sequence_mgr.get_visible_sequences()
                        if visible_seqs:
                            for seq in visible_seqs:
                                yield Button(seq.label, id=f"seq_{seq.id}", variant=seq.variant)
                        else:
                            yield Label("Aucune séquence configurée.", classes="info_muted")
            with TabPane("Parameters", id="tab_parameters"):
                with Vertical(id="params_container"):
                    yield Label("⚙️ Automatisation & Paramètres :", classes="section_title")
                    yield Checkbox("Auto Help", id="chk_auto_help", value=self.auto_help_enabled)
                    yield Checkbox("Auto Loot", id="chk_auto_loot", value=self.auto_loot_enabled)
            with TabPane("Debug", id="tab_debug"):
                with Horizontal(id="buttons"):
                    yield Button("Screen", id="screen_button", variant="success")
                    yield Button("Save ROIs", id="save_rois_button", variant="primary")
                    yield Button("Tracking: ON", id="toggle_tracking_button", variant="error")
                yield Log(id="console")
        yield Footer()

    async def update_actions(
        self,
        state: Optional[str],
        visible_buttons: Optional[Union[set, list, dict]] = None,
    ) -> None:
        """Met à jour dynamiquement les boutons d'actions selon l'état actuel et la visibilité des boutons."""
        actions = self.action_mgr.get_actions(state, visible_buttons=visible_buttons)
        action_ids = [act.id for act in actions]
        if action_ids == self.displayed_actions:
            return
        self.displayed_actions = action_ids

        regular_actions = [act for act in actions if act.id != "return"]
        return_act = next((act for act in actions if act.id == "return"), None)

        try:
            container = self.query_one("#action_buttons", ItemGrid)
            await container.remove_children()
            if regular_actions:
                for action in regular_actions:
                    await container.mount(Button(action.label, id=f"act_{action.id}", variant=action.variant))
            elif not return_act:
                await container.mount(Label("Aucune action disponible pour cet état.", classes="info_muted"))

            bottom_container = self.query_one("#bottom_actions", Horizontal)
            await bottom_container.remove_children()
            if return_act:
                await bottom_container.mount(Button(return_act.label, id=f"act_{return_act.id}", variant="error"))
        except Exception:
            pass

    async def update_actions_for_state(self, state: Optional[str]) -> None:
        """Compatibilité descendante pour mise à jour par état."""
        await self.update_actions(state, getattr(self, "last_visible_buttons", None))

    def on_mount(self) -> None:
        self.query_one("#console", Log).write_line(
            f"⚡ {self.preloaded_count} templates préchargés en RAM ({self.lang.upper()})"
        )
        self.query_one("#console", Log).write_line("🚀 Démarrage du thread d'analyse continue des états...")
        self.state_supervisor()

    def on_unmount(self) -> None:
        self._stop_tracking.set()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        key = (event.checkbox.id or "").replace("chk_", "")
        self.settings[key] = event.value
        status = "activé" if event.value else "désactivé"
        self.query_one("#console", Log).write_line(f"⚙️ Paramètre : {event.checkbox.label} {status}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if event.button.id == "screen_button":
            self.query_one("#console", Log).write_line("Démarrage du worker screen...")
            self.screenshot()
        elif event.button.id == "save_rois_button":
            self.query_one("#console", Log).write_line("Démarrage de la sauvegarde des ROIs...")
            self.save_rois()
        elif event.button.id == "toggle_tracking_button":
            self.tracking_enabled = not self.tracking_enabled
            if self.tracking_enabled:
                event.button.label = "Tracking: ON"
                event.button.variant = "error"
                self.query_one("#console", Log).write_line("▶️ Surveillance automatique réactivée")
            else:
                event.button.label = "Tracking: OFF"
                event.button.variant = "default"
                self.query_one("#console", Log).write_line("⏸️ Surveillance automatique mise en pause")
        elif btn_id.startswith("act_"):
            action_id = btn_id[4:]
            action = self.action_mgr.get(action_id)
            if action:
                self.query_one("#console", Log).write_line(f"⚡ Action '{action.label}' déclenchée...")
                if action.drag:
                    self.action_drag(action)
                else:
                    self.action_click_button(action)
        elif btn_id.startswith("seq_"):
            seq_id = btn_id[4:]
            sequence = self.sequence_mgr.get(seq_id)
            if sequence:
                self.run_sequence(sequence.id)

    def _find_and_click_button(
        self,
        button_names: List[str],
        hold_duration: Optional[float] = None,
        timeout: float = 4.0,
        restore_cursor: bool = False,
        action_name: str = "",
        log_ui: Any = None,
    ) -> bool:
        """Recherche et clique sur l'un des boutons demandés avec un délai d'attente (timeout)."""
        game_window = self.game_window
        if not game_window.exists():
            if log_ui:
                log_ui("⚠️ Fenêtre 'Last War' introuvable.")
            return False

        start_time = time.time()
        while True:
            if self._stop_tracking.is_set():
                return False

            shot = game_window.capture()
            if shot:
                resolved_rois = self.roi_reg.resolve_all(shot.width, shot.height)
                arr = np.frombuffer(shot.rgb, dtype=np.uint8).reshape((shot.height, shot.width, 3))
                crops = {}
                for name, roi in resolved_rois.items():
                    top = max(0, min(shot.height, roi.top))
                    bottom = max(0, min(shot.height, roi.top + roi.height))
                    left = max(0, min(shot.width, roi.left))
                    right = max(0, min(shot.width, roi.left + roi.width))
                    crops[name] = arr[top:bottom, left:right]

                visible = self.button_mgr.detect_visible_buttons(crops, target_names=button_names)
                candidates = [visible[b] for b in button_names if b in visible]
                if candidates:
                    target = max(candidates, key=lambda m: m.score)
                    cx, cy = target.center(resolved_rois)
                    duration = hold_duration if hold_duration is not None else target.hold_duration
                    target.click(
                        game_window,
                        resolved_rois,
                        restore_cursor=restore_cursor,
                        human_like=True,
                        speed_factor=self.mouse_speed_factor,
                        hold_duration=duration,
                    )
                    hold_info = f" (maintien {duration}s)" if duration else ""
                    tag = f"[Action {action_name}]" if action_name else "[Clic]"
                    if log_ui:
                        log_ui(f"⚡ {tag} Clic effectué sur '{target.name}' à ({cx}, {cy}){hold_info}")
                    return True

            if timeout > 0 and (time.time() - start_time < timeout):
                time.sleep(0.15)
            else:
                break

        tag = f"[Action {action_name}]" if action_name else "[Clic]"
        if log_ui:
            log_ui(f"⚠️ {tag} Bouton introuvable parmi : {', '.join(button_names)}")
        return False

    def _wait_for_state(
        self,
        target_state: Union[str, List[str]],
        timeout: float = 5.0,
        log_ui: Any = None,
    ) -> bool:
        """Attend qu'un état donné soit atteint dans le jeu avec un timeout."""
        if isinstance(target_state, (list, tuple, set)):
            targets = [str(s).strip().lower() for s in target_state if str(s).strip()]
        elif isinstance(target_state, str):
            clean = target_state.strip("[]() ")
            targets = [s.strip().strip("'\"").lower() for s in clean.split(",") if s.strip()]
        else:
            targets = [str(target_state).strip().lower()] if target_state else []

        if not targets:
            if log_ui:
                log_ui("ℹ️ [Wait State] Aucun état cible spécifié, poursuite...")
            return True

        start_time = time.time()
        while True:
            if self._stop_tracking.is_set():
                return False

            cur = (self.current_state or "").lower()
            if cur in targets:
                if log_ui:
                    log_ui(f"⏳ [Wait State] État '{cur}' atteint ({time.time() - start_time:.2f}s).")
                return True

            # Analyse immédiate via capture si la fenêtre existe
            if self.game_window.exists():
                shot = self.game_window.capture()
                if shot:
                    rois = self.roi_reg.resolve_all(shot.width, shot.height)
                    arr = np.frombuffer(shot.rgb, dtype=np.uint8).reshape((shot.height, shot.width, 3))
                    crops = {}
                    for name, roi in rois.items():
                        top = max(0, min(shot.height, roi.top))
                        bottom = max(0, min(shot.height, roi.top + roi.height))
                        left = max(0, min(shot.width, roi.left))
                        right = max(0, min(shot.width, roi.left + roi.width))
                        crops[name] = arr[top:bottom, left:right]
                    det_st, _, _ = self.state_mgr.resolve_state(crops)
                    if det_st:
                        self.current_state = det_st
                        if det_st.lower() in targets:
                            if log_ui:
                                log_ui(f"⏳ [Wait State] État '{det_st}' atteint ({time.time() - start_time:.2f}s).")
                            return True

            if timeout > 0 and (time.time() - start_time < timeout):
                time.sleep(0.15)
            else:
                break

        if log_ui:
            log_ui(f"⚠️ [Wait State] Timeout ({timeout}s) en attente de l'état : {', '.join(targets)} (état actuel : '{self.current_state}')")
        return False

    @work(thread=True)

    def action_drag(self, action: Any) -> None:
        import pyautogui
        import time
        from model.roi import ROISpec
        
        log_ui = lambda msg: self.call_from_thread(self.query_one("#console", Log).write_line, msg)
        
        if action.cooldown > 0 and time.time() - action.last_triggered < action.cooldown:
            log_ui(f"⏳ Action '{action.label}' ignorée (cooldown de {action.cooldown}s).")
            return
            
        drag = action.drag
        win = self.game_window
        if not win or not win.exists():
            log_ui("⚠️ Impossible d'exécuter le drag : fenêtre de jeu introuvable.")
            return
            
        geom = win.get_geometry()
        if not geom:
            return
            
        start_x, start_y = 0, 0
        if drag.type == "relative":
            btn_id = next((b for b in action.buttons if b in self.last_visible_buttons), None)
            if not btn_id:
                log_ui(f"⚠️ Action '{action.label}': Aucun bouton visible pour démarrer le drag.")
                return
            _, match_data = self.last_visible_buttons[btn_id]
            start_x = match_data['pos'][0] + match_data['size'][0] // 2
            start_y = match_data['pos'][1] + match_data['size'][1] // 2
        elif drag.type == "roi":
            if not drag.start_roi: return
            start_spec = self.roi_reg.get(drag.start_roi)
            if not start_spec: return
            res = start_spec.resolve(geom.width, geom.height)
            start_x = geom.left + res.left + res.width // 2
            start_y = geom.top + res.top + res.height // 2
        elif drag.type == "ab":
            temp_roi = ROISpec(name="temp_from", x=drag.from_coord.get("x"), y=drag.from_coord.get("y"), width=1, height=1)
            res = temp_roi.resolve(geom.width, geom.height)
            start_x = geom.left + res.x
            start_y = geom.top + res.y
            
        end_x, end_y = start_x, start_y
        if drag.type == "relative":
            end_x = start_x + (drag.dx or 0)
            end_y = start_y + (drag.dy or 0)
        elif drag.type == "roi":
            if not drag.end_roi: return
            end_spec = self.roi_reg.get(drag.end_roi)
            if not end_spec: return
            res = end_spec.resolve(geom.width, geom.height)
            end_x = geom.left + res.left + res.width // 2
            end_y = geom.top + res.top + res.height // 2
        elif drag.type == "ab":
            temp_roi = ROISpec(name="temp_to", x=drag.to_coord.get("x"), y=drag.to_coord.get("y"), width=1, height=1)
            res = temp_roi.resolve(geom.width, geom.height)
            end_x = geom.left + res.x
            end_y = geom.top + res.y
            
        orig_mouse = None
        if action.save_mouse:
            orig_mouse = pyautogui.position()
            
        pyautogui.moveTo(start_x, start_y)
        time.sleep(0.05)
        pyautogui.mouseDown(button="left")
        time.sleep(0.1)
        pyautogui.moveTo(end_x, end_y, duration=drag.duration)
        time.sleep(0.2)
        pyautogui.mouseUp(button="left")
        
        if orig_mouse:
            pyautogui.moveTo(*orig_mouse)
            
        action.last_triggered = time.time()

    @work(thread=True)
    def action_click_button(
        self,
        action: Any,
        log_ui: Any = None,
    ) -> None:
        if log_ui is None:
            log_ui = lambda msg: self.call_from_thread(self.query_one("#console", Log).write_line, msg)
            
        import time
        if action.cooldown > 0 and time.time() - action.last_triggered < action.cooldown:
            log_ui(f"⏳ Action '{action.label}' ignorée (cooldown de {action.cooldown}s).")
            return
            
        try:
            success = self._find_and_click_button(
                action.buttons,
                hold_duration=action.hold_duration,
                timeout=0.0,
                restore_cursor=action.save_mouse,
                action_name=action.label,
                log_ui=log_ui,
            )
            if success:
                action.last_triggered = time.time()
        except Exception as e:
            log_ui(f"⚠️ Erreur lors de l'action : {e}")

    @work(thread=True)
    def run_sequence(self, sequence_id: str) -> None:
        log_ui = lambda msg: self.call_from_thread(self.query_one("#console", Log).write_line, msg)
        seq = self.sequence_mgr.get(sequence_id)
        if not seq:
            log_ui(f"⚠️ Séquence '{sequence_id}' introuvable.")
            return

        if self._action_in_progress:
            log_ui("⚠️ Une action ou séquence est déjà en cours d'exécution.")
            return

        self._action_in_progress = True
        log_ui(f"▶️ Démarrage de la séquence : '{seq.label}' ({len(seq.steps)} étapes)...")

        orig_pos = pyautogui.position()
        try:
            ok = self._execute_sequence(seq, log_ui=log_ui, depth=0)
            if ok:
                log_ui(f"✅ Séquence '{seq.label}' terminée avec succès.")
            else:
                log_ui(f"⚠️ Séquence '{seq.label}' interrompue.")
        except Exception as e:
            log_ui(f"⚠️ Erreur lors de la séquence '{seq.label}' : {e}")
        finally:
            try:
                human_move(orig_pos.x, orig_pos.y, speed_factor=self.mouse_speed_factor)
            except Exception:
                pass
            self._action_in_progress = False

    def _execute_sequence(self, seq: SequenceSpec, log_ui: Any, depth: int = 0) -> bool:
        if depth > 5:
            log_ui("⚠️ Limite de récursion atteinte dans les séquences.")
            return False

        for idx, step in enumerate(seq.steps, 1):
            if self._stop_tracking.is_set():
                log_ui("🛑 Arrêt demandé pendant la séquence.")
                return False

            stype = step.type.lower()
            if stype == "action":
                act_spec = self.action_mgr.get(step.value)
                is_optional = bool(step.kwargs.get("optional", False))
                timeout_val = float(step.kwargs.get("timeout", 2.5 if is_optional else 5.0))
                
                if act_spec and act_spec.drag:
                    clicked = False
                    if act_spec.drag.type == "relative":
                        start_t = time.time()
                        while time.time() - start_t < timeout_val:
                            win = self.get_game_window()
                            if win:
                                self.refresh_rois(win, self.roi_reg.resolve_all(win.width, win.height))
                            if any(b in self.last_visible_buttons for b in act_spec.buttons):
                                self.action_drag(act_spec)
                                clicked = True
                                break
                            time.sleep(0.1)
                    else:
                        self.action_drag(act_spec)
                        clicked = True
                else:
                    if act_spec:
                        buttons = act_spec.buttons
                        hold = act_spec.hold_duration
                        label = act_spec.label
                    else:
                        buttons = [step.value]
                        hold = None
                        label = step.value

                    clicked = self._find_and_click_button(
                        buttons,
                        hold_duration=hold,
                        timeout=timeout_val,
                        restore_cursor=False,
                        action_name=label,
                        log_ui=log_ui,
                    )
                if not clicked:
                    if is_optional:
                        log_ui(f"ℹ️ [Action {label}] Non trouvée (étape optionnelle), poursuite...")
                    else:
                        log_ui(f"⚠️ Échec de l'étape {idx} (action '{step.value}'). Arrêt de la séquence.")
                        return False

            elif stype == "click":
                is_optional = bool(step.kwargs.get("optional", False))
                if step.value == "current_position":
                    time.sleep(random.uniform(0.04, 0.08))
                    pyautogui.mouseDown(button="left")
                    time.sleep(random.uniform(0.03, 0.05))
                    pyautogui.mouseUp(button="left")
                    pos = pyautogui.position()
                    log_ui(f"🖱️ [Clic] Clic effectué à la position actuelle ({pos.x}, {pos.y})")
                else:
                    if is_optional:
                        log_ui(f"ℹ️ Clic '{step.value}' ignoré (optionnel)...")
                    else:
                        log_ui(f"⚠️ Type de clic non supporté : '{step.value}'")

            elif stype == "sequence":
                sub_seq = self.sequence_mgr.get(step.value)
                is_optional = bool(step.kwargs.get("optional", False) or (sub_seq and sub_seq.optional))
                if not sub_seq:
                    if is_optional:
                        log_ui(f"ℹ️ Sous-séquence '{step.value}' introuvable (optionnelle), poursuite...")
                        continue
                    else:
                        log_ui(f"⚠️ Sous-séquence '{step.value}' introuvable.")
                        return False

                log_ui(f"↪️ Sous-séquence '{sub_seq.label}' en cours...")
                sub_ok = self._execute_sequence(sub_seq, log_ui=log_ui, depth=depth + 1)
                if not sub_ok:
                    if is_optional:
                        log_ui(f"ℹ️ Sous-séquence '{sub_seq.label}' non terminée (optionnelle), poursuite de la séquence...")
                    else:
                        return False

            elif stype == "wait_state":
                target_state = step.value
                is_optional = bool(step.kwargs.get("optional", False))
                timeout_val = float(step.kwargs.get("timeout", 5.0))

                log_ui(f"⏳ Attente de l'état '{target_state}'...")
                reached = self._wait_for_state(target_state, timeout=timeout_val, log_ui=log_ui)
                if not reached:
                    if is_optional:
                        log_ui(f"ℹ️ État '{target_state}' non atteint (étape optionnelle), poursuite...")
                    else:
                        log_ui(f"⚠️ Échec de l'étape {idx} (attente état '{target_state}'). Arrêt de la séquence.")
                        return False

            elif stype == "script":
                script_path = step.value
                is_optional = bool(step.kwargs.get("optional", False))
                log_ui(f"📜 Exécution du script Python : '{script_path}'...")
                try:
                    import importlib.util
                    import sys
                    from pathlib import Path
                    
                    path = Path(script_path)
                    if not path.is_absolute():
                        path = Path.cwd() / path
                        
                    if not path.exists():
                        log_ui(f"⚠️ Script introuvable : {path}")
                        if not is_optional: return False
                    else:
                        mod_spec = importlib.util.spec_from_file_location("custom_script", str(path))
                        if mod_spec and mod_spec.loader:
                            custom_module = importlib.util.module_from_spec(mod_spec)
                            sys.modules["custom_script"] = custom_module
                            mod_spec.loader.exec_module(custom_module)
                            if hasattr(custom_module, "run"):
                                custom_module.run(self)
                                log_ui(f"✅ Script '{script_path}' terminé avec succès.")
                            else:
                                log_ui(f"⚠️ Le script '{script_path}' ne contient pas de fonction 'run(app)'.")
                                if not is_optional: return False
                except Exception as e:
                    import traceback
                    log_ui(f"❌ Erreur lors de l'exécution du script '{script_path}': {str(e)}")
                    traceback.print_exc()
                    if not is_optional: return False

            else:
                log_ui(f"⚠️ Type d'étape inconnu : '{stype}' (valeur: {step.value})")

            # Pause configurée ou délai minimal de transition
            if step.sleep is not None and step.sleep > 0:
                time.sleep(step.sleep)
            else:
                time.sleep(0.3)

        return True

    @work(thread=True)
    def screenshot(self) -> None:

        log_ui = lambda msg: self.call_from_thread(self.query_one("#console", Log).write_line, msg)

        try:
            log_ui("Recherche de la fenêtre du jeu...")
            game_window = Window("Last War")

            if not game_window.exists():
                log_ui("Fenêtre 'Last War' introuvable.")
            else:
                geom = game_window.get_geometry()
                log_ui(f"Fenêtre détectée : '{game_window.title}' (PID: {game_window.pid}) : {geom.width}x{geom.height} à ({geom.left}, {geom.top})")
                
                # Ciblage / activation de la fenêtre
                log_ui("Activation de la fenêtre...")
                game_window.activate()

                # Capture d'écran directement en mémoire (sans écriture disque)
                shot = game_window.capture()
                if shot:
                    log_ui(f"Capture en mémoire réussie : {shot.width}x{shot.height} px ({len(shot.rgb)} octets RGB)")

            log_ui("Séquence terminée avec succès !")
        except Exception as e:
            log_ui(f"Erreur : {e}")

    @work(thread=True)
    def save_rois(self) -> None:
        log_ui = lambda msg: self.call_from_thread(self.query_one("#console", Log).write_line, msg)

        try:
            log_ui("Recherche de la fenêtre du jeu...")
            game_window = Window("Last War")

            if not game_window.exists():
                log_ui("Fenêtre 'Last War' introuvable.")
                return

            geom = game_window.get_geometry()
            log_ui(f"Fenêtre détectée : '{game_window.title}' ({geom.width}x{geom.height})")

            # Ciblage / activation
            log_ui("Activation de la fenêtre...")
            game_window.activate()

            # Capture d'écran en mémoire
            log_ui("Capture d'écran...")
            shot = game_window.capture()
            if not shot:
                log_ui("Échec de la capture d'écran.")
                return

            # Chargement de la configuration des ROIs
            config_path = Path(__file__).parent.parent / "config" / "rois.yaml"
            if not config_path.exists():
                log_ui(f"Fichier de configuration introuvable : {config_path}")
                return

            registry = ROIRegistry(config_path)
            resolved_rois = registry.resolve_all(geom.width, geom.height)

            out_dir = Path("screenshots") / "rois"
            out_dir.mkdir(parents=True, exist_ok=True)

            pil_img = Image.frombytes("RGB", shot.size, shot.rgb)

            for name, roi in resolved_rois.items():
                roi_crop = roi.crop_pillow(pil_img)
                target_file = out_dir / f"{name}.png"
                roi_crop.save(target_file)
                log_ui(f"ROI '{name}' ({roi.width}x{roi.height}) enregistrée sous '{target_file}'")

            log_ui(f"Succès : {len(resolved_rois)} ROI(s) enregistrée(s) dans '{out_dir}/'")
        except Exception as e:
            log_ui(f"Erreur lors de la sauvegarde des ROIs : {e}")

    @work(thread=True)
    def state_supervisor(self) -> None:
        log_ui = lambda msg: self.call_from_thread(self.query_one("#console", Log).write_line, msg)
        update_banner = lambda text: self.call_from_thread(self.query_one("#state_banner", Label).update, text)

        roi_reg = self.roi_reg
        state_mgr = self.state_mgr
        button_mgr = self.button_mgr

        last_state = None
        last_buttons = set()

        game_window = self.game_window

        while not self._stop_tracking.is_set():
            if not self.tracking_enabled:
                time.sleep(0.5)
                continue

            try:
                if not game_window.exists():
                    if last_state != "__NOT_FOUND__":
                        update_banner("⚠️ Fenêtre 'Last War' introuvable")
                        log_ui("⚠️ Fenêtre 'Last War' introuvable, en attente...")
                        last_state = "__NOT_FOUND__"
                    time.sleep(1.0)
                    continue

                shot = game_window.capture()
                if not shot:
                    time.sleep(self.poll_interval)
                    continue

                resolved_rois = roi_reg.resolve_all(shot.width, shot.height)
                arr = np.frombuffer(shot.rgb, dtype=np.uint8).reshape((shot.height, shot.width, 3))
                crops = {}
                for name, roi in resolved_rois.items():
                    top = max(0, min(shot.height, roi.top))
                    bottom = max(0, min(shot.height, roi.top + roi.height))
                    left = max(0, min(shot.width, roi.left))
                    right = max(0, min(shot.width, roi.left + roi.width))
                    crops[name] = arr[top:bottom, left:right]

                detected_state, score, details = state_mgr.resolve_state(crops)
                self.current_state = detected_state
                visible_buttons = button_mgr.detect_visible_buttons(crops, current_state=detected_state)
                current_button_names = set(visible_buttons.keys())

                self.last_resolved_rois = resolved_rois
                self.last_visible_buttons = visible_buttons

                if detected_state != last_state:
                    old_s = (last_state or "INITIALISATION").upper()
                    new_s = detected_state.upper()
                    update_banner(f"🎮 Current state: [bold cyan]{new_s}[/bold cyan] ({score:.0%})")
                    details_str = ", ".join(f"{k}: {v:.1%}" for k, v in details.items()) if details else ""
                    log_ui(f"🔄 New state: [{new_s}] ({score:.1%}) {details_str}")
                    last_state = detected_state

                # Filtrage continu des actions selon la présence réelle de leurs boutons dans le jeu
                self.call_from_thread(self.update_actions, detected_state, current_button_names)

                if current_button_names != last_buttons:
                    added = current_button_names - last_buttons
                    removed = last_buttons - current_button_names
                    if added:
                        added_str = "\n".join(f"{b} ({visible_buttons[b].score:.0%})" for b in added)
                        log_ui(f"🔘 New buttons:\n{added_str}")
                    if removed:
                        removed_str = "\n".join(removed)
                        log_ui(f"🔘 Disappeared buttons:\n{removed_str}")
                    last_buttons = current_button_names

                # Traitement déclaratif des boutons automatiques (seulement si aucune séquence en cours)
                if not self._action_in_progress:
                    for name, match in visible_buttons.items():
                        btn_spec = button_mgr.get(name)
                        if btn_spec and btn_spec.auto and self.settings.get(btn_spec.auto):
                            if btn_spec.can_trigger():
                                cx, cy = match.center(resolved_rois)
                                if btn_spec.execute(
                                    match,
                                    game_window,
                                    resolved_rois,
                                    human_like=True,
                                    speed_factor=self.mouse_speed_factor,
                                ):
                                    hold_info = f" (maintien {btn_spec.hold_duration}s)" if btn_spec.hold_duration else ""
                                    log_ui(f"⚡ [Auto] Clic sur '{name}' à ({cx}, {cy}){hold_info}")

            except Exception as e:
                log_ui(f"⚠️ Erreur superviseur : {e}")

            time.sleep(self.poll_interval)


if __name__ == "__main__":
    app = Lwsc()
    app.run()