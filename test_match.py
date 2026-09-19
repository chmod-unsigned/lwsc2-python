import cv2
import numpy as np
import sys
import glob

# Find the images
crop_files = glob.glob('screenshot*/roi/map_pane.png') + glob.glob('screenshot*/*/map_pane.png') + glob.glob('**/map_pane.png', recursive=True)
template_files = glob.glob('templates/**/mine_food.png', recursive=True) + glob.glob('**/mine_food.png', recursive=True)

if not crop_files:
    print("Crop not found")
    sys.exit(1)
if not template_files:
    print("Template not found")
    sys.exit(1)

crop_path = crop_files[0]
tpl_path = template_files[0]

print(f"Using crop: {crop_path}")
print(f"Using template: {tpl_path}")

crop = cv2.imread(crop_path, cv2.IMREAD_GRAYSCALE)
tpl = cv2.imread(tpl_path, cv2.IMREAD_GRAYSCALE)

res = cv2.matchTemplate(crop, tpl, cv2.TM_CCOEFF_NORMED)
min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)

print(f"Score: {max_val}")
print(f"Location: {max_loc}")
