import cv2
import numpy as np

crop = cv2.imread('screenshots/rois/map_pane.png', cv2.IMREAD_GRAYSCALE)
tpl = cv2.imread('templates/en/poi/mine_food.png', cv2.IMREAD_GRAYSCALE)

orb = cv2.ORB_create(nfeatures=50000)
tpl_kp, tpl_des = orb.detectAndCompute(tpl, None)
crop_kp, crop_des = orb.detectAndCompute(crop, None)

bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
matches = bf.match(tpl_des, crop_des)
matches = sorted(matches, key=lambda x: x.distance)

good = [m for m in matches if m.distance <= 64]
print(f"Total template features: {len(tpl_kp)}")
print(f"Total crop features: {len(crop_kp)}")
print(f"Good matches <= 64: {len(good)}")

if len(good) >= 5:
    src_pts = np.float32([tpl_kp[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst_pts = np.float32([crop_kp[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    M, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)
    if mask is not None:
        inliers = np.sum(mask)
        print(f"Inliers: {inliers}")
    else:
        print("Homography failed")
