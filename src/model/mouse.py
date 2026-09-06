import time
import math
import random
from typing import Optional, Tuple
import pyautogui

# Désactiver les délais par défaut bloquants de PyAutoGUI
pyautogui.PAUSE = 0.0
pyautogui.MINIMUM_DURATION = 0.0


def human_move(
    target_x: int,
    target_y: int,
    speed_factor: float = 3.0,
    from_pos: Optional[Tuple[int, int]] = None,
) -> None:
    """
    Déplace le curseur de souris de manière fluide et naturelle vers (target_x, target_y)
    en utilisant une trajectoire de Bézier cubique avec accélération et décélération (ease-in-out).
    
    :param target_x: Coordonnée X absolue d'arrivée
    :param target_y: Coordonnée Y absolue d'arrivée
    :param speed_factor: Facteur de vitesse. 1.0 = vitesse humaine normale (~0.5s),
                         3.0 = 'human x3' (~0.15s à 0.25s, rapide mais visible et réaliste).
    :param from_pos: Coordonnée initiale optionnelle (si None, position actuelle du curseur)
    """
    if from_pos is not None:
        x0, y0 = from_pos
    else:
        current = pyautogui.position()
        x0, y0 = current.x, current.y

    dx = target_x - x0
    dy = target_y - y0
    dist = math.hypot(dx, dy)

    if dist < 4:
        pyautogui.moveTo(target_x, target_y)
        return

    # Durée proportionnelle à la distance selon Fitts' law simplifiée
    # Vitesse 'human x3' : environ 0.12s à 0.25s
    base_duration = max(0.08, min(0.30, (dist / 2500.0) + 0.08))
    duration = base_duration / (max(0.5, speed_factor) / 3.0)

    steps = max(10, min(30, int(duration * 120)))
    sleep_dt = duration / steps

    # Déviation légère pour courbure naturelle non linéaire (Bézier cubique)
    angle = math.atan2(dy, dx)
    deviation = min(35.0, dist * 0.08) * random.uniform(0.3, 0.8) * (1 if random.random() > 0.5 else -1)

    p1_x = x0 + dx * 0.3 - math.sin(angle) * deviation
    p1_y = y0 + dy * 0.3 + math.cos(angle) * deviation
    p2_x = x0 + dx * 0.7 - math.sin(angle) * deviation
    p2_y = y0 + dy * 0.7 + math.cos(angle) * deviation

    for i in range(1, steps + 1):
        r = i / steps
        # Easing cubic smoothstep (démarrage doux, rapide au milieu, décélération à l'arrivée)
        t = r * r * (3 - 2 * r)
        u = 1 - t
        cx = u**3 * x0 + 3 * u**2 * t * p1_x + 3 * u * t**2 * p2_x + t**3 * target_x
        cy = u**3 * y0 + 3 * u**2 * t * p1_y + 3 * u * t**2 * p2_y + t**3 * target_y
        pyautogui.moveTo(int(cx), int(cy))
        time.sleep(sleep_dt)

    pyautogui.moveTo(target_x, target_y)


def human_click(
    target_x: int,
    target_y: int,
    restore_cursor: bool = False,
    speed_factor: float = 3.0,
    hold_duration: Optional[float] = None,
    stay_clicked: Optional[float] = None,
) -> bool:
    """
    Exécute un clic complet réaliste :
    1. Déplacement courbé et progressif (human x3).
    2. Micro-pause d'arrivée (temps d'ajustement humain : 20-40 ms).
    3. Enfoncement du bouton gauche (durée normale : 30-50 ms, ou maintien prolongé si hold_duration est défini).
    4. Relâchement du bouton.
    5. Restauration fluide du curseur à son emplacement initial si restore_cursor=True.
    """
    orig_pos = pyautogui.position()
    orig_x, orig_y = orig_pos.x, orig_pos.y
    duration = hold_duration if hold_duration is not None else stay_clicked

    try:
        # 1. Déplacement naturel vers la cible
        human_move(target_x, target_y, speed_factor=speed_factor)

        # 2. Micro-pause avant clic
        time.sleep(random.uniform(0.02, 0.04))

        # 3. Clic humain (descente, maintien, remontée)
        pyautogui.mouseDown(button="left")
        if duration is not None and duration > 0:
            time.sleep(duration)
        else:
            time.sleep(random.uniform(0.03, 0.05))
        pyautogui.mouseUp(button="left")

        # 4. Restauration naturelle si demandée
        if restore_cursor:
            time.sleep(random.uniform(0.02, 0.04))
            human_move(orig_x, orig_y, speed_factor=speed_factor)

        return True
    except Exception:
        return False
