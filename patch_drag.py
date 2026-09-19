import re

# 1. Update action.py
with open("src/model/action.py", "r") as f:
    content = f.read()

imports = "from typing import Dict, List, Optional, Union, Any"
content = re.sub(r'from typing import Dict, List, Optional, Union', imports, content)

dragspec = """
@dataclass
class DragSpec:
    type: str = "relative"
    dx: Optional[int] = None
    dy: Optional[int] = None
    start_roi: Optional[str] = None
    end_roi: Optional[str] = None
    from_coord: Optional[Dict[str, Any]] = None
    to_coord: Optional[Dict[str, Any]] = None
    duration: float = 0.5
"""
content = re.sub(r'class ActionSpec:', dragspec + '\nclass ActionSpec:', content)

action_spec_update = "    hold_duration: Optional[float] = None\n    drag: Optional[DragSpec] = None"
content = content.replace("    hold_duration: Optional[float] = None", action_spec_update)

load_yaml_update = """
            drag_raw = spec.get("drag")
            drag_val = None
            if drag_raw and isinstance(drag_raw, dict):
                drag_val = DragSpec(
                    type=drag_raw.get("type", "relative"),
                    dx=drag_raw.get("dx"),
                    dy=drag_raw.get("dy"),
                    start_roi=drag_raw.get("start"),
                    end_roi=drag_raw.get("end"),
                    from_coord=drag_raw.get("from"),
                    to_coord=drag_raw.get("to"),
                    duration=float(drag_raw.get("duration", 0.5)),
                )

            self.actions[str(action_id)] = ActionSpec(
                id=str(action_id),
                label=label,
                states=states,
                buttons=buttons,
                variant=variant,
                hold_duration=hold_val,
                drag=drag_val,
            )"""
content = re.sub(r'            self.actions\[str\(action_id\)\] = ActionSpec\([\s\S]*?hold_duration=hold_val,\n            \)', load_yaml_update, content)

with open("src/model/action.py", "w") as f:
    f.write(content)


# 2. Update lwsc.py
with open("src/lwsc.py", "r") as f:
    content = f.read()

action_drag_method = """
    def action_drag(self, action: Any) -> None:
        import pyautogui
        import time
        from src.model.roi import ROISpec
        
        drag = action.drag
        win = self.get_game_window()
        if not win:
            log_ui("⚠️ Impossible d'exécuter le drag : fenêtre de jeu introuvable.")
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
            res = start_spec.resolve(win.width, win.height)
            start_x = win.left + res.left + res.width // 2
            start_y = win.top + res.top + res.height // 2
        elif drag.type == "ab":
            temp_roi = ROISpec(name="temp_from", x=drag.from_coord.get("x"), y=drag.from_coord.get("y"), width=1, height=1)
            res = temp_roi.resolve(win.width, win.height)
            start_x = win.left + res.x
            start_y = win.top + res.y
            
        end_x, end_y = start_x, start_y
        if drag.type == "relative":
            end_x = start_x + (drag.dx or 0)
            end_y = start_y + (drag.dy or 0)
        elif drag.type == "roi":
            if not drag.end_roi: return
            end_spec = self.roi_reg.get(drag.end_roi)
            if not end_spec: return
            res = end_spec.resolve(win.width, win.height)
            end_x = win.left + res.left + res.width // 2
            end_y = win.top + res.top + res.height // 2
        elif drag.type == "ab":
            temp_roi = ROISpec(name="temp_to", x=drag.to_coord.get("x"), y=drag.to_coord.get("y"), width=1, height=1)
            res = temp_roi.resolve(win.width, win.height)
            end_x = win.left + res.x
            end_y = win.top + res.y
            
        pyautogui.moveTo(start_x, start_y)
        time.sleep(0.05)
        pyautogui.mouseDown(button="left")
        time.sleep(0.1)
        pyautogui.moveTo(end_x, end_y, duration=drag.duration)
        time.sleep(0.2)
        pyautogui.mouseUp(button="left")
"""
content = re.sub(r'    def action_click_button\(', action_drag_method + '\n    def action_click_button(', content)

manual_trigger_update = """            if action:
                self.query_one("#console", Log).write_line(f"⚡ Action '{action.label}' déclenchée...")
                if action.drag:
                    self.action_drag(action)
                else:
                    self.action_click_button(
                        action.label,
                        *action.buttons,
                        hold_duration=action.hold_duration,
                    )"""
content = re.sub(r'            if action:\n                self.query_one\("#console", Log\).write_line.*?hold_duration=action.hold_duration,\n                \)', manual_trigger_update, content, flags=re.DOTALL)

seq_trigger_update = """                act_spec = self.action_mgr.get(step.value)
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
                    )"""
content = re.sub(r'                act_spec = self.action_mgr.get\(step.value\)[\s\S]*?log_ui=log_ui,\n                \)', seq_trigger_update, content)

with open("src/lwsc.py", "w") as f:
    f.write(content)
