import cv2
import numpy as np

crop = cv2.imread('screenshots/rois/map_pane.png', cv2.IMREAD_GRAYSCALE)
tpl = cv2.imread('templates/en/poi/mine_food.png', cv2.IMREAD_GRAYSCALE)

best_score = 0
best_loc = None
best_scale = 1.0

# Test scales from 0.2 to 1.5
scales = np.linspace(0.2, 1.5, 20)
for scale in scales:
    width = int(tpl.shape[1] * scale)
    height = int(tpl.shape[0] * scale)
    if width < 10 or height < 10 or width > crop.shape[1] or height > crop.shape[0]:
        continue
    
    resized_tpl = cv2.resize(tpl, (width, height))
    res = cv2.matchTemplate(crop, resized_tpl, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    
    if max_val > best_score:
        best_score = max_val
        best_loc = max_loc
        best_scale = scale

print(f"Best Score: {best_score}")
print(f"Best Scale: {best_scale}")
print(f"Best Location: {best_loc}")
