import re

with open("src/model/matcher.py", "r") as f:
    content = f.read()

# Add ORB caches in __init__
init_patch = """        self._cache_sub2: Dict[str, np.ndarray] = {}
        self._cache_orb_kp: Dict[str, Any] = {}
        self._cache_orb_des: Dict[str, np.ndarray] = {}
        self._orb = None"""
content = content.replace("        self._cache_sub2: Dict[str, np.ndarray] = {}", init_patch)


# Add ORB init in preload_templates
preload_patch = """        weights = np.array([0.299, 0.587, 0.114], dtype=np.float32)
        
        try:
            import cv2
            self._orb = cv2.ORB_create(nfeatures=500)
        except ImportError:
            self._orb = None
"""
content = content.replace("        weights = np.array([0.299, 0.587, 0.114], dtype=np.float32)", preload_patch)


# Add ORB descriptor extraction in preload_templates
orb_extract_patch = """                        self._cache_sub4[resolved_str] = arr_gray[::4, ::4]
                        self._cache_sub2[resolved_str] = arr_gray[::2, ::2]
                        
                        if self._orb is not None:
                            kp, des = self._orb.detectAndCompute(arr_gray.astype(np.uint8), None)
                            self._cache_orb_kp[resolved_str] = kp
                            self._cache_orb_des[resolved_str] = des"""
content = content.replace("                        self._cache_sub4[resolved_str] = arr_gray[::4, ::4]\n                        self._cache_sub2[resolved_str] = arr_gray[::2, ::2]", orb_extract_patch)


orb_cache_patch = """                    self._cache_sub4[file_path.name] = self._cache_sub4[resolved_str]
                    self._cache_sub2[file_path.name] = self._cache_sub2[resolved_str]
                    
                    if self._orb is not None:
                        self._cache_orb_kp[file_path.name] = self._cache_orb_kp[resolved_str]
                        self._cache_orb_des[file_path.name] = self._cache_orb_des[resolved_str]"""
content = content.replace("                    self._cache_sub4[file_path.name] = self._cache_sub4[resolved_str]\n                    self._cache_sub2[file_path.name] = self._cache_sub2[resolved_str]", orb_cache_patch)


# Update method signatures to accept method
sig1 = """    def compute_similarity(
        self,
        crop: Union[Image.Image, np.ndarray, Path, str],
        template: Union[Image.Image, np.ndarray, Path, str],
        color: bool = True,
        method: str = "exact",
    ) -> float:
        \"\"\"Calcule le score de similarité (de 0.0 à 1.0) entre une ROI et un template.\"\"\"
        return self.match_detailed(crop, template, color=color, method=method)[0]"""
content = re.sub(r'    def compute_similarity.*?return self\.match_detailed\(crop, template, color=color\)\[0\]', sig1, content, flags=re.DOTALL)

sig2 = """    def match_detailed(
        self,
        crop: Union[Image.Image, np.ndarray, Path, str],
        template: Union[Image.Image, np.ndarray, Path, str],
        color: bool = True,
        method: str = "exact",
    ) -> Tuple[float, Tuple[int, int], Tuple[int, int]]:
        \"\"\"
        Calcule le score de similarité, la position (x, y) et la taille (w, h) du template.
        Retourne : (score, (match_x, match_y), (template_w, template_h)).
        \"\"\"
        if method == "feature":
            return self._match_orb(crop, template)"""
content = re.sub(r'    def match_detailed.*?Retourne : \(score, \(match_x, match_y\), \(template_w, template_h\)\)\.\n        \"\"\"', sig2, content, flags=re.DOTALL)


# Add _match_orb method at the end
orb_method = """
    def _match_orb(self, crop, template) -> Tuple[float, Tuple[int, int], Tuple[int, int]]:
        try:
            import cv2
        except ImportError:
            return (0.0, (0, 0), (0, 0))
            
        if self._orb is None:
            self._orb = cv2.ORB_create(nfeatures=500)
        
        crop_gray = self.to_gray_array(crop).astype(np.uint8)
        
        # Get template descriptors
        str_key = str(template) if isinstance(template, (str, Path)) else None
        
        if str_key and str_key in self._cache_orb_des:
            tpl_kp = self._cache_orb_kp[str_key]
            tpl_des = self._cache_orb_des[str_key]
            tpl_gray = self.to_gray_array(template)
            th, tw = tpl_gray.shape[:2]
        else:
            tpl_gray = self.to_gray_array(template).astype(np.uint8)
            th, tw = tpl_gray.shape[:2]
            tpl_kp, tpl_des = self._orb.detectAndCompute(tpl_gray, None)
            
        if tpl_des is None or len(tpl_kp) < 5:
            return (0.0, (0, 0), (tw, th))
            
        crop_kp, crop_des = self._orb.detectAndCompute(crop_gray, None)
        if crop_des is None or len(crop_kp) < 5:
            return (0.0, (0, 0), (tw, th))
            
        bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        matches = bf.match(tpl_des, crop_des)
        matches = sorted(matches, key=lambda x: x.distance)
        
        # Calculate score based on number of good matches
        # 15-20 matches is usually enough for a solid match in a game UI
        good_matches = [m for m in matches if m.distance < 50]
        score = min(1.0, len(good_matches) / 20.0) 
        
        if len(good_matches) < 5:
            return (score, (0, 0), (tw, th))
            
        # Extract coordinates of good matches
        src_pts = np.float32([tpl_kp[m.queryIdx].pt for m in good_matches]).reshape(-1, 1, 2)
        dst_pts = np.float32([crop_kp[m.trainIdx].pt for m in good_matches]).reshape(-1, 1, 2)
        
        # Find homography to get bounding box
        M, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)
        
        if M is None:
            # Fallback to centroid of matches if homography fails
            centroid_x = int(np.mean(dst_pts[:, 0, 0]))
            centroid_y = int(np.mean(dst_pts[:, 0, 1]))
            # Estimate roughly centered bounding box
            return (score, (max(0, centroid_x - tw//2), max(0, centroid_y - th//2)), (tw, th))
            
        h, w = th, tw
        pts = np.float32([[0, 0], [0, h - 1], [w - 1, h - 1], [w - 1, 0]]).reshape(-1, 1, 2)
        try:
            dst = cv2.perspectiveTransform(pts, M)
            x_coords = dst[:, 0, 0]
            y_coords = dst[:, 0, 1]
            min_x, max_x = np.min(x_coords), np.max(x_coords)
            min_y, max_y = np.min(y_coords), np.max(y_coords)
            
            match_w = int(max_x - min_x)
            match_h = int(max_y - min_y)
            return (score, (int(min_x), int(min_y)), (match_w, match_h))
        except Exception:
            return (score, (0, 0), (tw, th))
"""
content = content + orb_method

# Also need to import Any
content = content.replace("from typing import Union, Optional, Tuple, Dict", "from typing import Union, Optional, Tuple, Dict, Any")

with open("src/model/matcher.py", "w") as f:
    f.write(content)
