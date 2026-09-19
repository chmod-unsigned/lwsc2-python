import time
import numpy as np

def run(app):
    app.query_one("#console").write_line("🚀 [Script] Démarrage de la récolte !")
    
    # Capture d'écran manuelle pour avoir l'état actuel de la fenêtre
    if not app.game_window or not app.game_window.exists():
        app.query_one("#console").write_line("❌ Erreur: Fenêtre de jeu introuvable.")
        return
        
    shot = app.game_window.capture()
    if not shot:
        app.query_one("#console").write_line("❌ Erreur: Capture d'écran impossible.")
        return
        
    arr = np.frombuffer(shot.rgb, dtype=np.uint8).reshape((shot.height, shot.width, 3))
    
    # On découpe l'écran selon nos ROI habituelles (ex: map_pane)
    rois = app.roi_reg.resolve_all(shot.width, shot.height)
    crops = {}
    for name, roi in rois.items():
        top = max(0, min(shot.height, roi.top))
        bottom = max(0, min(shot.height, roi.top + roi.height))
        left = max(0, min(shot.width, roi.left))
        right = max(0, min(shot.width, roi.left + roi.width))
        crops[name] = arr[top:bottom, left:right]
        
    # On demande au bot de lister TOUTES les mines
    resultats = app.button_mgr.detect_all_visible_buttons(crops, target_names=["poi_mine_food"]) #, "poi_mine_iron", "poi_mine_gold"])
    
    total_found = sum(len(matches) for matches in resultats.values())
    if total_found == 0:
        app.query_one("#console").write_line("ℹ️ Aucune mine trouvée à l'écran.")
        return
        
    # resultats est un dictionnaire: {"poi_mine_food": [ButtonMatch, ButtonMatch...], ...}
    for btn_name, matches in resultats.items():
        app.query_one("#console").write_line(f"🎯 Trouvé {len(matches)} occurrences de {btn_name}")
        for idx, match in enumerate(matches, 1):
            app.query_one("#console").write_line(f"   -> Clic sur la mine {idx}/{len(matches)} (score: {match.score:.2f})")
            
            # On clique !
            match.click(
                app.game_window,
                rois,
                human_like=True,
                speed_factor=app.mouse_speed_factor
            )
            
            # Petite pause entre les clics pour laisser le jeu réagir
            time.sleep(0.8)
            
    app.query_one("#console").write_line("✅ [Script] Récolte terminée !")
