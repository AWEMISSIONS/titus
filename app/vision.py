from __future__ import annotations

import json
import math
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np


VEHICLE_CLASSES = {2: "Car", 3: "Motorcycle", 5: "Bus", 7: "Truck"}
PERSON_CLASSES = {0: "Person"}
ANIMAL_CLASSES = {
    14: "Bird", 15: "Cat", 16: "Dog", 17: "Horse", 18: "Sheep",
    19: "Cow", 20: "Elephant", 21: "Bear", 22: "Zebra", 23: "Giraffe"
}
TARGET_CLASSES = {**VEHICLE_CLASSES, **PERSON_CLASSES, **ANIMAL_CLASSES}
CATEGORY_BY_CLASS = {cid: "vehicle" for cid in VEHICLE_CLASSES}
CATEGORY_BY_CLASS.update({cid: "person" for cid in PERSON_CLASSES})
CATEGORY_BY_CLASS.update({cid: "animal" for cid in ANIMAL_CLASSES})


@dataclass
class Detection:
    track_id: int
    class_id: int
    category: str
    label: str
    confidence: float
    xyxy: tuple[int, int, int, int]
    center: tuple[int, int]
    color: str = ""
    zone: str = ""
    is_moving: bool = False
    motion_score: float = 0.0
    speed_mph: Optional[float] = None
    speed_confidence: float = 0.0
    speed_source: str = ""
    persistent_id: str = ""
    persistent_match: float = 0.0
    display_name: str = ""


def crop_with_pad(frame: np.ndarray, xyxy, pad_ratio: float = 0.08) -> np.ndarray:
    x1, y1, x2, y2 = xyxy
    px = int((x2 - x1) * pad_ratio)
    py = int((y2 - y1) * pad_ratio)
    x1, y1 = max(0, x1 - px), max(0, y1 - py)
    x2, y2 = min(frame.shape[1], x2 + px), min(frame.shape[0], y2 + py)
    return frame[y1:y2, x1:x2]


def night_enhance(frame: np.ndarray, threshold: float = 78.0, enabled: bool = True):
    sample = cv2.resize(frame, (160, 90), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(sample, cv2.COLOR_BGR2GRAY)
    brightness = float(np.median(gray))
    if not enabled or brightness >= threshold:
        return frame, brightness, False, 0.0

    strength = max(0.0, min(1.0, (threshold - brightness) / max(threshold, 1.0)))
    gamma = max(0.48, 1.0 - 0.52 * strength)
    lut = np.array([((i / 255.0) ** gamma) * 255.0 for i in range(256)], dtype=np.uint8)
    lifted = cv2.LUT(frame, lut)

    lab = cv2.cvtColor(lifted, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=1.7 + 1.3 * strength, tileGridSize=(8, 8))
    l = clahe.apply(l)
    enhanced = cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)
    alpha = 0.35 + 0.55 * strength
    out = cv2.addWeighted(enhanced, alpha, frame, 1.0 - alpha, 0.0)
    return out, brightness, True, strength


def quality_metrics(frame: np.ndarray, brightness: float) -> dict:
    small = cv2.resize(frame, (320, 180), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if brightness < 18:
        label = "Too dark"
    elif sharpness < 18:
        label = "Blurry"
    elif brightness < 35 or sharpness < 35:
        label = "Fair"
    elif brightness > 235:
        label = "Overexposed"
    elif sharpness >= 85:
        label = "Excellent"
    else:
        label = "Good"
    return {"label": label, "brightness": brightness, "sharpness": sharpness}


def estimate_color(crop: np.ndarray) -> str:
    if crop is None or crop.size == 0:
        return "Unknown"
    h, w = crop.shape[:2]
    roi = crop[int(h*0.25):int(h*0.75), int(w*0.20):int(w*0.80)]
    if roi.size == 0:
        roi = crop
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    pixels = hsv.reshape(-1, 3)
    value = pixels[:, 2]
    if float(np.percentile(value, 65)) < 58:
        return "Unknown"
    mask = (pixels[:, 2] > 35) & (pixels[:, 2] < 245)
    if mask.any():
        pixels = pixels[mask]
    if not len(pixels):
        return "Unknown"
    H = float(np.median(pixels[:, 0]))
    S = float(np.median(pixels[:, 1]))
    V = float(np.median(pixels[:, 2]))
    if V < 65:
        return "Black"
    if S < 28 and V > 190:
        return "White"
    if S < 38:
        return "Gray/Silver"
    if H < 8 or H >= 172:
        return "Red"
    if H < 18:
        return "Orange/Brown"
    if H < 34:
        return "Yellow/Gold"
    if H < 85:
        return "Green"
    if H < 132:
        return "Blue"
    if H < 160:
        return "Purple"
    return "Red"


class MotionTracker:
    def __init__(self):
        self.history: dict[int, deque] = {}
        self.moving: set[int] = set()
        self.confirm: dict[int, int] = {}

    def reset(self):
        self.history.clear()
        self.moving.clear()
        self.confirm.clear()

    def forget(self, track_id: int):
        self.history.pop(track_id, None)
        self.confirm.pop(track_id, None)
        self.moving.discard(track_id)

    def update(self, track_id: int, center, shape, now: float, sensitivity: float, category: str):
        h, w = shape[:2]
        diag = max(math.hypot(w, h), 1.0)
        hist = self.history.setdefault(track_id, deque(maxlen=24))
        hist.append((now, int(center[0]), int(center[1])))
        while hist and now - hist[0][0] > 1.25:
            hist.popleft()
        if len(hist) < 4:
            return False, 0.0

        _, x0, y0 = hist[0]
        _, x1, y1 = hist[-1]
        net = math.hypot(x1-x0, y1-y0) / diag
        steps = [
            math.hypot(b[1]-a[1], b[2]-a[2]) / diag
            for a, b in zip(hist, list(hist)[1:])
        ]
        med = float(np.median(steps)) if steps else 0.0
        sens = max(1.0, min(10.0, float(sensitivity)))
        threshold = 0.0165 - (sens - 1.0) * (0.0125 / 9.0)
        step_threshold = threshold / 7.0
        score = max(net / max(threshold, 1e-6), med / max(step_threshold, 1e-6))

        raw = net >= threshold and med >= step_threshold * 0.45
        count = self.confirm.get(track_id, 0)
        if raw and score >= 0.95:
            count = min(12, count + 1)
        else:
            count = max(0, count - 2)
        self.confirm[track_id] = count

        required = 4 if category == "vehicle" else 2
        moving = raw and count >= required
        if moving:
            self.moving.add(track_id)
        elif track_id in self.moving and score < 0.25:
            self.moving.discard(track_id)
        return track_id in self.moving, score


class AutoSpeedEstimator:
    NOMINAL_FT = {"Car": 15.0, "Truck": 18.5, "Bus": 35.0, "Motorcycle": 7.0}

    def __init__(self):
        self.history: dict[int, deque] = {}
        self.ema: dict[int, float] = {}

    def reset(self):
        self.history.clear()
        self.ema.clear()

    def forget(self, track_id: int):
        self.history.pop(track_id, None)
        self.ema.pop(track_id, None)

    def update(self, det: Detection, now: float, scale: float = 1.0, night: bool = False):
        if det.category != "vehicle" or not det.is_moving:
            return None
        x1, y1, x2, y2 = det.xyxy
        size = max(float(x2-x1), float(y2-y1)*1.6, 1.0)
        hist = self.history.setdefault(det.track_id, deque(maxlen=28))
        hist.append((now, float(det.center[0]), float(det.center[1]), size))
        while hist and now - hist[0][0] > 1.2:
            hist.popleft()
        if len(hist) < 5 or hist[-1][0] - hist[0][0] < 0.28:
            return None

        samples = []
        for a, b in zip(hist, list(hist)[1:]):
            dt = max(b[0]-a[0], 1e-4)
            dist = math.hypot(b[1]-a[1], b[2]-a[2])
            midsize = max((a[3]+b[3])*0.5, 1.0)
            samples.append((dist/dt)/midsize)
        norm = float(np.median(samples))
        mph = norm * self.NOMINAL_FT.get(det.label, 15.0) * 0.6818181818 * float(scale)
        if not 1.0 <= mph <= 120.0:
            return None
        prev = self.ema.get(det.track_id)
        smooth = mph if prev is None else 0.72*prev + 0.28*mph
        self.ema[det.track_id] = smooth

        stability = 1.0 - min(1.0, float(np.std(samples))/max(norm, 0.001))
        duration = min(1.0, (hist[-1][0]-hist[0][0])/0.9)
        confidence = 0.30 + 0.35*stability + 0.35*duration
        if night:
            confidence *= 0.78
        return float(smooth), max(0.20, min(0.88, confidence))


def _dhash(crop: np.ndarray) -> str:
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    diff = small[:, 1:] > small[:, :-1]
    value = 0
    for bit in diff.flatten():
        value = (value << 1) | int(bit)
    return f"{value:016x}"


def fingerprint(crop: np.ndarray) -> Optional[str]:
    if crop is None or crop.size == 0 or crop.shape[0] < 18 or crop.shape[1] < 18:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0,1], None, [12,8], [0,180,0,256])
    hist = cv2.normalize(hist, hist).flatten().astype(float)
    h, w = crop.shape[:2]
    data = {"hist": hist.tolist(), "hash": _dhash(crop), "aspect": float(w/max(h,1))}
    return json.dumps(data)


def fingerprint_similarity(a_text: str, b_text: str, color_a: str, color_b: str, type_a: str, type_b: str):
    try:
        a, b = json.loads(a_text), json.loads(b_text)
        ha = np.asarray(a["hist"], dtype=np.float32)
        hb = np.asarray(b["hist"], dtype=np.float32)
        hist_sim = 1.0 - float(cv2.compareHist(ha, hb, cv2.HISTCMP_BHATTACHARYYA))
        hash_sim = 1.0 - ((int(a["hash"],16)^int(b["hash"],16)).bit_count()/64.0)
        aspect_sim = max(0.0, 1.0-abs(math.log(max(a["aspect"],.01)/max(b["aspect"],.01)))/1.2)
    except Exception:
        return 0.0
    color_sim = 1.0 if color_a == color_b else (0.55 if {color_a,color_b} <= {"Gray/Silver","White","Black"} else 0.15)
    type_sim = 1.0 if type_a == type_b else (0.55 if {type_a,type_b} <= {"Car","Truck","Bus"} else 0.0)
    return 0.36*hist_sim + 0.34*hash_sim + 0.10*aspect_sim + 0.10*color_sim + 0.10*type_sim


class ZoneManager:
    def __init__(self, settings_store):
        self.settings_store = settings_store

    def zone_at(self, center, shape) -> str:
        h, w = shape[:2]
        x, y = center[0]/max(w,1), center[1]/max(h,1)
        zones = self.settings_store.data["zones"]
        for name in ("ignore","driveway","sidewalk","road"):
            r = zones.get(name)
            if r and r[0] <= x <= r[2] and r[1] <= y <= r[3]:
                return name
        return ""

    def set_zone(self, name: str, rect):
        x1,y1,x2,y2 = rect
        x1,x2 = sorted((max(0,min(1,x1)), max(0,min(1,x2))))
        y1,y2 = sorted((max(0,min(1,y1)), max(0,min(1,y2))))
        if x2-x1 < .01 or y2-y1 < .01:
            return
        self.settings_store.data["zones"][name] = [x1,y1,x2,y2]
        self.settings_store.save()

    def clear_zone(self, name: str):
        self.settings_store.data["zones"][name] = None
        self.settings_store.save()

    def draw(self, frame: np.ndarray):
        colors = {
            "road": (255,170,0), "driveway": (0,255,255),
            "sidewalk": (255,100,220), "ignore": (120,120,120)
        }
        h,w = frame.shape[:2]
        for name,r in self.settings_store.data["zones"].items():
            if not r:
                continue
            x1,y1,x2,y2 = int(r[0]*w),int(r[1]*h),int(r[2]*w),int(r[3]*h)
            c = colors[name]
            cv2.rectangle(frame,(x1,y1),(x2,y2),c,2)
            cv2.putText(frame,name.upper(),(x1+5,max(20,y1+20)),cv2.FONT_HERSHEY_SIMPLEX,.55,c,2)


class HeadlightAssist:
    def __init__(self):
        self.history = deque(maxlen=8)

    def reset(self):
        self.history.clear()

    def detect(self, frame: np.ndarray):
        h,w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        t = max(205, int(np.percentile(gray,99.35)))
        _,mask = cv2.threshold(gray,t,255,cv2.THRESH_BINARY)
        mask = cv2.morphologyEx(mask,cv2.MORPH_OPEN,np.ones((3,3),np.uint8))
        mask = cv2.dilate(mask,np.ones((5,5),np.uint8),iterations=1)
        n,labels,stats,cents = cv2.connectedComponentsWithStats(mask)
        blobs=[]
        for i in range(1,n):
            x,y,bw,bh,area=stats[i]
            if 8 <= area <= w*h*0.012 and y >= h*0.20:
                blobs.append((x,y,bw,bh,area,cents[i][0],cents[i][1]))
        best,best_score=None,0.0
        for i in range(len(blobs)):
            for j in range(i+1,len(blobs)):
                a,b=blobs[i],blobs[j]
                dx,dy=abs(a[5]-b[5]),abs(a[6]-b[6])
                avg_h=max((a[3]+b[3])*.5,1.0)
                if dx < avg_h or dx > w*.28 or dy > max(18,avg_h*1.8):
                    continue
                ratio=min(a[4],b[4])/max(a[4],b[4])
                if ratio < .20:
                    continue
                score=.45+.30*ratio+.25*(1-min(1,dy/max(dx,1)))
                if score>best_score:
                    x1=int(min(a[0],b[0])-dx*.35); x2=int(max(a[0]+a[2],b[0]+b[2])+dx*.35)
                    y1=int(min(a[1],b[1])-avg_h*2); y2=int(max(a[1]+a[3],b[1]+b[3])+avg_h*2.4)
                    best=(max(0,x1),max(0,y1),min(w-1,x2),min(h-1,y2))
                    best_score=score
        if best is None:
            return None,0.0
        now=time.time(); cx=(best[0]+best[2])*.5; cy=(best[1]+best[3])*.5
        self.history.append((now,cx,cy))
        while self.history and now-self.history[0][0]>1.2:
            self.history.popleft()
        if len(self.history)>=3:
            _,x0,y0=self.history[0]; _,x1,y1=self.history[-1]
            move=math.hypot(x1-x0,y1-y0)/max(math.hypot(w,h),1)
            if move<.004:
                return best,min(.55,best_score*.62)
            best_score += min(.18,move*8)
        return best,float(max(0,min(1,best_score)))
