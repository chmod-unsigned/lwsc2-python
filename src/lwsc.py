import time
import threading
import random
import pyautogui
import sys
if sys.platform == 'win32':
    try:
        import pydirectinput as _mouse
        _mouse.PAUSE = 0.0
    except ImportError:
        _mouse = pyautogui
else:
    _mouse = pyautogui
import numpy as np
import os
from pathlib import Path
from typing import Dict, List, Optional, Any, Union, Set
from PIL import Image

import tkinter as tk
from tkinter import ttk
from pynput import keyboard

from model.window import Window
from model.roi import ROIRegistry
from model.matcher import ImageMatcher
from model.state import StateManager
from model.button import ButtonManager
from model.action import ActionManager
from model.sequence import SequenceManager, SequenceSpec, SequenceStep
from model.mouse import human_move


class Lwsc:
    lang: str = "en"
    poll_interval: float = 0.05  # Fréquence d'analyse : jusqu'à 20 fois par seconde (instantané)

    def __init__(self):
        project_root = Path(__file__).resolve().parent.parent
        config_dir = project_root / "config"
        
        self.settings_file = config_dir / "settings.yaml"
        self.settings: Dict[str, Any] = self.load_settings()
        # Apply stored language
        self.lang = self.settings.get("language", "en")
        # Load translation dictionary
        import yaml
        lang_file = config_dir / "lang" / f"{self.lang}.yaml"
        self.translations = yaml.safe_load(open(lang_file, "r", encoding="utf-8")) if lang_file.exists() else {}

        self.root = tk.Tk()
        self.root.title(self.translations.get("ui.title", "LWSC"))
        self.root.geometry("800x600")
        self.root.attributes("-topmost", True)

        self._stop_tracking = threading.Event()
        self.stop_action_event = threading.Event()
        self.play_event = threading.Event()
        self.play_event.set()
        self.tracking_enabled = True
        self.last_resolved_rois: Dict[str, Any] = {}
        self.last_visible_buttons: Dict[str, Any] = {}

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

        self.setup_ui()
        self.root.withdraw()

    def load_settings(self) -> Dict[str, Any]:
        import yaml
        default_settings = {
            "auto_help": False,
            "auto_loot": False,
            "language": "en",
            "shortcuts": {
                "toggle_window": {"key": "<ctrl>+w", "description": "shortcuts.toggle_window.description"},
                "toggle_tracking": {"key": "<ctrl>+p", "description": "shortcuts.toggle_tracking.description"},
                "stop_action": {"key": "<ctrl>+s", "description": "shortcuts.stop_action.description"}
            }
        }
        if not self.settings_file.exists():
            return default_settings
        try:
            with open(self.settings_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                if isinstance(data, dict):
                    default_settings.update(data)
        except Exception as e:
            print(f"Error loading settings: {e}")
        return default_settings

    def save_settings(self) -> None:
        import yaml
        try:
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                yaml.dump(self.settings, f)
        except Exception as e:
            print(f"Error saving settings: {e}")

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



    def update_actions(self, state: Optional[str], visible_buttons: Optional[Union[set, list, dict]] = None) -> None:
        self.root.after(0, self._update_actions_gui, state, visible_buttons)

    def on_language_change(self, event=None) -> None:
        """Handler for language selection changes"""
        new_lang = self.language_var.get()
        if new_lang and new_lang != self.lang:
            self.lang = new_lang
            self.settings["language"] = new_lang
            self.save_settings()
            self.log_message(f"⚙️ Language changed to {new_lang}")
            # Reinitialize components that depend on language
            # Simple approach: recreate matcher, state_mgr, button_mgr with new lang
            project_root = Path(__file__).resolve().parent.parent
            config_dir = project_root / "config"
            self.matcher = ImageMatcher(templates_root=project_root / "templates", lang=self.lang)
            self.matcher.preload_templates()
            self.roi_reg = ROIRegistry(config_dir / "rois.yaml")
            self.state_mgr = StateManager(config_dir / "states.yaml", templates_root=project_root / "templates", lang=self.lang, matcher=self.matcher)
            self.button_mgr = ButtonManager(config_dir / "buttons.yaml", templates_root=project_root / "templates", lang=self.lang, matcher=self.matcher)
            # Refresh UI labels where needed (shortcuts will be reloaded on next UI update)
            self.log_message("🛈 UI components refreshed for new language.")
        
    def _update_actions_gui(self, state: Optional[str], visible_buttons: Optional[Union[set, list, dict]] = None) -> None:
        all_actions = self.action_mgr.get_actions_for_state(state)
        v_set = set(visible_buttons.keys()) if isinstance(visible_buttons, dict) else (set(visible_buttons) if visible_buttons else set())
        
        action_states = []
        for act in all_actions:
            is_enabled = act.always_show or not act.buttons or any(b in v_set for b in act.buttons)
            action_states.append((act, is_enabled))
            
        current_state_sig = [(act.id, is_enabled) for act, is_enabled in action_states]
        if hasattr(self, 'displayed_actions_sig') and getattr(self, 'displayed_actions_sig') == current_state_sig:
            return
        self.displayed_actions_sig = current_state_sig
        
        for widget in self.actions_frame.winfo_children():
            widget.destroy()
        for widget in self.bottom_actions_frame.winfo_children():
            widget.destroy()
            
        regular_actions = [item for item in action_states if item[0].id != "return"]
        return_act_item = next((item for item in action_states if item[0].id == "return"), None)
        
        if regular_actions:
            for act, is_enabled in regular_actions:
                btn = ttk.Button(self.actions_frame, text=self.translations.get(act.label, act.label), command=lambda a=act.id: self.start_action(a))
                if not is_enabled:
                    btn.state(['disabled'])
                btn.pack(fill=tk.X, pady=2)
        elif not return_act_item:
            tk.Label(self.actions_frame, text=self.translations.get("ui.no_actions", "Aucune action disponible pour cet état."), fg="gray").pack()
            
        if return_act_item:
            act, is_enabled = return_act_item
            btn = ttk.Button(self.bottom_actions_frame, text=self.translations.get(act.label, act.label), command=lambda a=act.id: self.start_action(a))
            if not is_enabled:
                btn.state(['disabled'])
            btn.pack(fill=tk.X, pady=2)

        self.root.after(10, self.resize_notebook)


    def setup_ui(self):
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        self.banner_var = tk.StringVar(value=self.translations.get("ui.banner_initial", "🎮 État du jeu : INITIALISATION..."))
        ttk.Label(main_frame, textvariable=self.banner_var).pack(fill=tk.X, pady=5)
        
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill=tk.BOTH, expand=False, pady=5)
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed)
        
        self.tab_actions = ttk.Frame(self.notebook)
        self.tab_sequences = ttk.Frame(self.notebook)
        self.tab_params = ttk.Frame(self.notebook)
        self.tab_debug = ttk.Frame(self.notebook)
        self.tab_help = ttk.Frame(self.notebook)
        
        self.notebook.add(self.tab_actions, text=self.translations.get("ui.tab_actions", "Actions"))
        self.notebook.add(self.tab_sequences, text=self.translations.get("ui.tab_sequences", "Sequences"))
        self.notebook.add(self.tab_params, text=self.translations.get("ui.tab_parameters", "Parameters"))
        self.notebook.add(self.tab_debug, text=self.translations.get("ui.tab_debug", "Debug"))
        self.notebook.add(self.tab_help, text=self.translations.get("ui.tab_help", "Help"))
        
        # Actions
        self.actions_frame = ttk.Frame(self.tab_actions)
        self.actions_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        self.bottom_actions_frame = ttk.Frame(self.tab_actions)
        self.bottom_actions_frame.pack(fill=tk.X, pady=5)
        
        # Sequences
        seq_frame = ttk.Frame(self.tab_sequences)
        seq_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        for seq in self.sequence_mgr.get_visible_sequences():
            ttk.Button(seq_frame, text=self.translations.get(seq.label, seq.label), command=lambda s=seq.id: self.start_sequence(s)).pack(fill=tk.X, pady=2)
            
        # Params
        self.auto_help_var = tk.BooleanVar(value=self.auto_help_enabled)
        self.auto_loot_var = tk.BooleanVar(value=self.auto_loot_enabled)
        ttk.Checkbutton(self.tab_params, text=self.translations.get("ui.auto_help", "Auto Help"), variable=self.auto_help_var, command=self.on_param_change).pack(anchor=tk.W)
        ttk.Checkbutton(self.tab_params, text=self.translations.get("ui.auto_loot", "Auto Loot"), variable=self.auto_loot_var, command=self.on_param_change).pack(anchor=tk.W)
        
        # Language selection
        ttk.Label(self.tab_params, text=self.translations.get("ui.language_label", "Language:" )).pack(anchor=tk.W, pady=(5,0))
        self.language_var = tk.StringVar(value=self.lang)
        # Determine available language files
        lang_dir = Path(__file__).resolve().parent.parent / "config" / "lang"
        available_langs = [p.stem for p in lang_dir.iterdir() if p.is_file() and p.suffix == ".yaml"]
        self.language_combo = ttk.Combobox(self.tab_params, textvariable=self.language_var, values=available_langs, state="readonly")
        self.language_combo.pack(fill=tk.X, pady=2)
        self.language_combo.bind("<<ComboboxSelected>>", self.on_language_change)
        
        # Load shortcuts
        shortcuts_data = self.settings.get("shortcuts", {})
                
        # Default fallback values if missing
        k_win = shortcuts_data.get("toggle_window", {}).get("key", "<ctrl>+w")
        k_trk = shortcuts_data.get("toggle_tracking", {}).get("key", "<ctrl>+p")
        k_stp = shortcuts_data.get("stop_action", {}).get("key", "<ctrl>+s")
        
        desc_win = self.translations.get(shortcuts_data.get("toggle_window", {}).get("description", "shortcuts.toggle_window.description"), "Afficher / Cacher la fenêtre")
        desc_trk = self.translations.get(shortcuts_data.get("toggle_tracking", {}).get("description", "shortcuts.toggle_tracking.description"), "Mettre en pause / Relancer le tracking")
        desc_stp = self.translations.get(shortcuts_data.get("stop_action", {}).get("description", "shortcuts.stop_action.description"), "Interrompre l'action")

        # Help
        help_frame = ttk.Frame(self.tab_help, padding=10)
        help_frame.pack(fill=tk.BOTH, expand=True)
        tk.Label(help_frame, text=self.translations.get("ui.help.global_shortcuts", "Raccourcis clavier globaux :"), font=("Helvetica", 10, "bold"), anchor="w").pack(fill=tk.X, pady=(0, 5))
        
        shortcuts_list = [
            (k_win, desc_win),
            (k_trk, desc_trk),
            (k_stp, desc_stp)
        ]
        
        for keys, desc in shortcuts_list:
            display_key = keys.replace("<ctrl>+", "Ctrl + ").replace("<shift>+", "Shift + ").replace("<alt>+", "Alt + ").upper()
            f = ttk.Frame(help_frame)
            f.pack(fill=tk.X, pady=2)
            tk.Label(f, text=display_key, font=("Helvetica", 9, "bold"), width=10, anchor="e").pack(side=tk.LEFT, padx=(0, 10))
            tk.Label(f, text=desc, anchor="w", justify=tk.LEFT, wraplength=400).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Debug
        btn_frame = ttk.Frame(self.tab_debug)
        btn_frame.pack(fill=tk.X, pady=5)
        ttk.Button(btn_frame, text=self.translations.get("ui.debug.screen", "Screen"), command=lambda: threading.Thread(target=self.screenshot, daemon=True).start()).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text=self.translations.get("ui.debug.save_rois", "Save ROIs"), command=lambda: threading.Thread(target=self.save_rois, daemon=True).start()).pack(side=tk.LEFT, padx=2)
        self.tracking_btn = ttk.Button(btn_frame, text=self.translations.get("ui.tracking.on", "Tracking: ON"), command=self.toggle_tracking)
        self.tracking_btn.pack(side=tk.LEFT, padx=2)
        
        
        self.console = tk.Text(main_frame, bg="black", fg="white", state=tk.DISABLED, height=8)
        self.console.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.log_message(f"⚡ {self.preloaded_count} templates préchargés en RAM ({self.lang.upper()})")
        self.log_message("🚀 Démarrage du thread d'analyse continue des états...")
        threading.Thread(target=self.state_supervisor, daemon=True).start()

        # Keyboard listener
        self.listener = keyboard.GlobalHotKeys({
            k_win: self.toggle_window,
            k_trk: lambda: self.root.after(0, self.toggle_tracking),
            k_stp: self.stop_current_action
        })
        self.listener.start()

    def on_tab_changed(self, event):
        self.resize_notebook()

    def resize_notebook(self):
        self.root.update_idletasks()
        try:
            tab = self.notebook.nametowidget(self.notebook.select())
            self.notebook.configure(height=tab.winfo_reqheight())
        except Exception:
            pass

    def toggle_window(self):
        self.root.after(0, self._toggle_window)

    def _toggle_window(self):
        import subprocess
        try:
            result = subprocess.run(["xdotool", "getactivewindow", "getwindowname"], capture_output=True, text=True, check=True)
            active_title = result.stdout.strip().lower()
            if "last war" not in active_title and "lwsc" not in active_title:
                return
        except Exception:
            pass

        if self.root.winfo_viewable():
            self.root.withdraw()
        else:
            self.root.deiconify()
            if not self.tracking_enabled:
                self.toggle_tracking()

    def start_sequence(self, seq_id):
        threading.Thread(target=self.run_sequence, args=(seq_id,), daemon=True).start()

    def start_action(self, action_id):
        action = self.action_mgr.get(action_id)
        if action:
            self.stop_action_event.clear()
            act_label_t = self.translations.get(action.label, action.label)
            self.log_message(f"⚡ Action '{act_label_t}' déclenchée...")
            if action.drag:
                threading.Thread(target=self.action_drag, args=(action,), daemon=True).start()
            else:
                threading.Thread(target=self.action_click_button, args=(action,), daemon=True).start()

    def stop_current_action(self):
        self.stop_action_event.set()
        self.root.after(0, lambda: self.log_message("🛑 Interruption de l'action/séquence demandée par l'utilisateur."))

    def on_param_change(self):
        self.auto_help_enabled = self.auto_help_var.get()
        self.auto_loot_enabled = self.auto_loot_var.get()
        # Update language if changed via combobox
        self.lang = self.language_var.get()
        self.settings["language"] = self.lang
        self.save_settings()
        self.log_message(f"⚙️ Auto Help: {self.auto_help_enabled}, Auto Loot: {self.auto_loot_enabled}, Language: {self.lang}")

    def toggle_tracking(self):
        self.tracking_enabled = not self.tracking_enabled
        if self.tracking_enabled:
            self.play_event.set()
            self.tracking_btn.config(text=self.translations.get("ui.tracking.on", "Tracking: ON"))
            self.log_message(self.translations.get("log.tracking_resumed", "▶️ Surveillance automatique réactivée"))
        else:
            self.play_event.clear()
            self.tracking_btn.config(text=self.translations.get("ui.tracking.off", "Tracking: OFF"))
            self.log_message(self.translations.get("log.tracking_paused", "⏸️ Surveillance automatique mise en pause"))

    def log_message(self, msg):
        self.console.config(state=tk.NORMAL)
        self.console.insert(tk.END, str(msg) + "\n")
        self.console.see(tk.END)
        self.console.config(state=tk.DISABLED)
        
    def update_banner_label(self, text):
        self.banner_var.set(text)
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
            if self._stop_tracking.is_set() or self.stop_action_event.is_set():
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
            if self._stop_tracking.is_set() or self.stop_action_event.is_set():
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

    
    def action_drag(self, action: Any) -> None:
        import pyautogui
        import sys
        if sys.platform == 'win32':
            try:
                import pydirectinput as _mouse
                _mouse.PAUSE = 0.0
            except ImportError:
                _mouse = pyautogui
        else:
            _mouse = pyautogui
        import time
        from model.roi import ROISpec
        
        log_ui = lambda msg: self.root.after(0, self.log_message, msg)
        
        if action.cooldown > 0 and time.time() - action.last_triggered < action.cooldown:
            act_label_t = self.translations.get(action.label, action.label)
            log_ui(f"⏳ Action '{act_label_t}' ignorée (cooldown de {action.cooldown}s).")
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
                act_label_t = self.translations.get(action.label, action.label)
                log_ui(f"⚠️ Action '{act_label_t}': Aucun bouton visible pour démarrer le drag.")
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
            
        _mouse.moveTo(start_x, start_y)
        time.sleep(0.05)
        _mouse.mouseDown(button="left")
        time.sleep(0.1)
        _mouse.moveTo(end_x, end_y, duration=drag.duration)
        time.sleep(0.2)
        _mouse.mouseUp(button="left")
        
        if orig_mouse:
            _mouse.moveTo(*orig_mouse)
            
        action.last_triggered = time.time()

    def action_click_button(
        self,
        action: Any,
        log_ui: Any = None,
    ) -> None:
        if log_ui is None:
            log_ui = lambda msg: self.root.after(0, self.log_message, msg)
            
        import time
        if action.cooldown > 0 and time.time() - action.last_triggered < action.cooldown:
            act_label_t = self.translations.get(action.label, action.label)
            log_ui(f"⏳ Action '{act_label_t}' ignorée (cooldown de {action.cooldown}s).")
            return
            
        try:
            success = self._find_and_click_button(
                action.buttons,
                hold_duration=action.hold_duration,
                timeout=0.0,
                restore_cursor=action.save_mouse,
                action_name=self.translations.get(action.label, action.label),
                log_ui=log_ui,
            )
            if success:
                action.last_triggered = time.time()
        except Exception as e:
            log_ui(f"⚠️ Erreur lors de l'action : {e}")

    def run_sequence(self, sequence_id: str) -> None:
        log_ui = lambda msg: self.root.after(0, self.log_message, msg)
        seq = self.sequence_mgr.get(sequence_id)
        if not seq:
            log_ui(f"⚠️ Séquence '{sequence_id}' introuvable.")
            return

        if self._action_in_progress:
            log_ui("⚠️ Une action ou séquence est déjà en cours d'exécution.")
            return

        self._action_in_progress = True
        self.stop_action_event.clear()
        seq_label_t = self.translations.get(seq.label, seq.label)
        log_ui(f"▶️ Démarrage de la séquence : '{seq_label_t}' ({len(seq.steps)} étapes)...")

        orig_pos = pyautogui.position()
        try:
            ok = self._execute_sequence(seq, log_ui=log_ui, depth=0)
            if ok:
                log_ui(f"✅ Séquence '{seq_label_t}' terminée avec succès.")
            else:
                log_ui(f"⚠️ Séquence '{seq_label_t}' interrompue.")
        except Exception as e:
            log_ui(f"⚠️ Erreur lors de la séquence '{seq_label_t}' : {e}")
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
            if self._stop_tracking.is_set() or self.stop_action_event.is_set():
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
                            if self._stop_tracking.is_set() or self.stop_action_event.is_set():
                                break
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
                        label = self.translations.get(act_spec.label, act_spec.label)
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
                    _mouse.mouseDown(button="left")
                    time.sleep(random.uniform(0.03, 0.05))
                    _mouse.mouseUp(button="left")
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

                seq_label_t = self.translations.get(sub_seq.label, sub_seq.label)
                log_ui(f"↪️ Sous-séquence '{seq_label_t}' en cours...")
                sub_ok = self._execute_sequence(sub_seq, log_ui=log_ui, depth=depth + 1)
                if not sub_ok:
                    if is_optional:
                        log_ui(f"ℹ️ Sous-séquence '{seq_label_t}' non terminée (optionnelle), poursuite de la séquence...")
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

    def screenshot(self) -> None:

        log_ui = lambda msg: self.root.after(0, self.log_message, msg)

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

    def save_rois(self) -> None:
        log_ui = lambda msg: self.root.after(0, self.log_message, msg)

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

    def state_supervisor(self) -> None:
        log_ui = lambda msg: self.root.after(0, self.log_message, msg)
        update_banner = lambda text: self.root.after(0, self.update_banner_label, text)

        roi_reg = self.roi_reg
        state_mgr = self.state_mgr
        button_mgr = self.button_mgr

        last_state = None
        last_buttons = set()

        game_window = self.game_window

        while not self._stop_tracking.is_set():
            self.play_event.wait()
            if self._stop_tracking.is_set():
                break

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
                    update_banner(f"State: {new_s} ({score:.0%})")
                    details_str = ", ".join(f"{k}: {v:.1%}" for k, v in details.items()) if details else ""
                    log_ui(f"🔄 New state: [{new_s}] ({score:.1%}) {details_str}")
                    last_state = detected_state

                # Filtrage continu des actions selon la présence réelle de leurs boutons dans le jeu
                self.update_actions(detected_state, current_button_names)

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



    class _MockConsole:
        def __init__(self, app):
            self.app = app
        def write_line(self, msg):
            self.app.root.after(0, self.app.log_message, msg)
            
    class _MockBanner:
        def __init__(self, app):
            self.app = app
        def update(self, msg):
            self.app.root.after(0, self.app.update_banner_label, msg)

    def query_one(self, selector: str, *args):
        if selector == "#console":
            return self._MockConsole(self)
        if selector == "#state_banner":
            return self._MockBanner(self)
        return None

    def call_from_thread(self, func, *args, **kwargs):
        self.root.after(0, lambda: func(*args, **kwargs))


if __name__ == "__main__":
    app = Lwsc()
    app.root.mainloop()
