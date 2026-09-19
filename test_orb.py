import cv2
import numpy as np

img = cv2.imread('./templates/en/poi/mine_food.png', cv2.IMREAD_GRAYSCALE)
orb = cv2.ORB_create(nfeatures=500)
kp, des = orb.detectAndCompute(img, None)
print(f"Keypoints detected: {len(kp)}")

bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
matches = bf.match(des, des)
matches = sorted(matches, key=lambda x: x.distance)

good_matches = [m for m in matches if m.distance < 50]
print(f"Good matches (dist < 50): {len(good_matches)}")
