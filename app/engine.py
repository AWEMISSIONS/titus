from __future__ import annotations

import math
import os
import queue
import re
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

import cv2
import numpy as np

from database import TitusDatabase
from settings import SettingsStore
from vision import (
    ANIMAL_CLASSES, CATEGORY_BY_CLASS, PERSON_CLASSES, TARGET_CLASSES, VEHICLE_CLASSES,
    AutoSpeedEstimator, Detection, HeadlightAssist, MotionTracker, ZoneManager,
    crop_with_pad, estimate_color, fingerprint, fingerprint_similarity,
    night_enhance, quality_metrics,
)


class TitusEngine:
    def __init__(
        self,
        app_dir: Path,
        db: TitusDatabase,
        settings: SettingsStore,
        frame_queue: queue.Queue,
        event_queue: queue.Queue,
    ):
        self.app_dir = app_dir
        self.db = db
        self.settings = settings
        self.frame_queue = frame_queue
        self.event_queue = event_queue

        self.model_path = app_dir / "yolo26n.pt"
        self.snapshot_dir = app_dir / "data" / "snapshots"
        self.identity_dir = app_dir / "data" / "identities"
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.identity_dir.mkdir(parents=True, exist_ok=True)

        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.cap: Optional[cv2.VideoCapture] = None
        self.model = None
        self.model_loading = False
        self.model_error = ""
        self.source: Union[int, str] = 0

        self.motion = MotionTracker()
        self.speed = AutoSpeedEstimator()
        self.headlights = HeadlightAssist()
        self.zones = ZoneManager(settings)

        self.track_seen: dict[int, int] = {}
        self.last_seen: dict[int, float] = {}
        self.previous_center: dict[int, tuple[int, int]] = {}
        self.previous_side: dict[int, int] = {}
        self.logged_tracks: set[int] = set()
        self.person_logged: set[int] = set()
        self.animal_logged: set[int] = set()
        self.track_event_id: dict[int, int] = {}
        self.track_event_code: dict[int, str] = {}
        self.track_identity: dict[int, tuple[str, str, float]] = {}
        self.best_crop: dict[int, tuple[float, np.ndarray]] = {}
        self.speed_by_track: dict[int, tuple[float, float, str]] = {}

        self.fps_ema = 0.0
        self.infer_ms_ema = 0.0
        self.frame_count = 0
        self.camera_fail_count = 0
        self.last_headlight_alert = 0.0

    def prepare_ai_async(self):
        if self.model is not None or self.model_loading:
            return
        threading.Thread(target=self._load_model, daemon=True, name="Titus-AI-Loader").start()

    def _load_model(self):
        self.model_loading = True
        self.model_error = ""
        try:
            self.event_queue.put(("status", "Loading local AI..."))
            from ultralytics import YOLO
            ref = str(self.model_path) if self.model_path.exists() else "yolo26n.pt"
            model = YOLO(ref)
            try:
                model.predict(np.zeros((480, 640, 3), dtype=np.uint8), imgsz=640, verbose=False)
            except Exception:
                pass
            self.model = model
            self.event_queue.put(("status", "AI ready" if not self.running else "Monitoring"))
        except Exception as exc:
            self.model_error = str(exc)
            self.event_queue.put(("error", f"AI could not load: {exc}"))
        finally:
            self.model_loading = False

    @staticmethod
    def _parse_source(source_text: str) -> Union[int, str]:
        text = source_text.strip()
        match = re.fullmatch(r"(?:Camera\s*)?(\d+)", text, flags=re.IGNORECASE)
        return int(match.group(1)) if match else text

    def start(self, source_text: str):
        if self.running:
            return
        self.source = self._parse_source(source_text)
        self._reset_session()
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True, name="Titus-Camera")
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None

    def _reset_session(self):
        self.motion.reset()
        self.speed.reset()
        self.headlights.reset()
        self.track_seen.clear()
        self.last_seen.clear()
        self.previous_center.clear()
        self.previous_side.clear()
        self.logged_tracks.clear()
        self.person_logged.clear()
        self.animal_logged.clear()
        self.track_event_id.clear()
        self.track_event_code.clear()
        self.track_identity.clear()
        self.best_crop.clear()
        self.speed_by_track.clear()
        self.frame_count = 0
        self.camera_fail_count = 0
        self.fps_ema = 0.0
        self.infer_ms_ema = 0.0

    def _open_camera(self):
        if not isinstance(self.source, int):
            return cv2.VideoCapture(self.source)

        last = None
        for backend in (cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY):
            cap = None
            try:
                cap = cv2.VideoCapture(self.source, backend)
                last = cap
                if not cap.isOpened():
                    cap.release()
                    continue
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                cap.set(cv2.CAP_PROP_FPS, 30)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                ok, frame = cap.read()
                if ok and frame is not None and frame.size:
                    return cap
                cap.release()
            except Exception:
                try:
                    if cap is not None:
                        cap.release()
                except Exception:
                    pass
        try:
            if last is not None:
                last.release()
        except Exception:
            pass
        return cv2.VideoCapture()

    def scan_cameras_async(self, max_index: int = 8):
        def worker():
            found = []
            for idx in range(max_index):
                for backend in (cv2.CAP_DSHOW, cv2.CAP_MSMF):
                    cap = None
                    try:
                        cap = cv2.VideoCapture(idx, backend)
                        if cap.isOpened():
                            ok, frame = cap.read()
                            if ok and frame is not None and frame.size:
                                found.append(idx)
                                break
                    except Exception:
                        pass
                    finally:
                        try:
                            if cap is not None:
                                cap.release()
                        except Exception:
                            pass
            self.event_queue.put(("camera_scan", sorted(set(found))))
        threading.Thread(target=worker, daemon=True, name="Titus-Camera-Scan").start()

    def _active_classes(self):
        s = self.settings.data
        ids = []
        if s.get("monitor_vehicles", True):
            ids += list(VEHICLE_CLASSES)
        if s.get("monitor_people", True):
            ids += list(PERSON_CLASSES)
        if s.get("monitor_animals", True):
            ids += list(ANIMAL_CLASSES)
        return ids or list(VEHICLE_CLASSES)

    def _run(self):
        try:
            self.cap = self._open_camera()
            if not self.cap.isOpened():
                raise RuntimeError(
                    f"Could not start camera {self.source}. Close Camera, Zoom, Teams, OBS, "
                    "or browser tabs that may be using it, then try again."
                )

            self.event_queue.put(("status", "Camera live — AI loading" if self.model is None else "Monitoring"))
            if self.model is None:
                self.prepare_ai_async()

            while self.running:
                loop_start = time.perf_counter()
                ok, raw = self.cap.read()
                if not ok or raw is None:
                    self.camera_fail_count += 1
                    if self.camera_fail_count >= 25:
                        self.event_queue.put(("status", "Camera reconnecting..."))
                        try:
                            self.cap.release()
                        except Exception:
                            pass
                        time.sleep(0.5)
                        self.cap = self._open_camera()
                        self.camera_fail_count = 0
                    else:
                        time.sleep(0.03)
                    continue
                self.camera_fail_count = 0
                self.frame_count += 1

                s = self.settings.data
                enhanced, brightness, night_active, night_strength = night_enhance(
                    raw,
                    float(s.get("night_threshold", 78.0)),
                    bool(s.get("night_assist", True)),
                )
                quality = quality_metrics(enhanced, brightness)

                if self.model is None:
                    annotated = enhanced.copy()
                    cv2.rectangle(annotated, (0,0), (annotated.shape[1],54), (18,18,18), -1)
                    cv2.putText(
                        annotated,
                        "CAMERA LIVE  |  LOCAL AI LOADING...",
                        (18,36), cv2.FONT_HERSHEY_SIMPLEX, .82, (0,220,255), 2,
                    )
                    self.zones.draw(annotated)
                    self._draw_tripwire(annotated)
                    self._publish_frame(annotated)
                    if self.frame_count % 8 == 0:
                        self._publish_stats([], brightness, night_active, night_strength, quality)
                    time.sleep(0.012)
                    continue

                infer_start = time.perf_counter()
                results = self.model.track(
                    enhanced,
                    persist=True,
                    tracker="bytetrack.yaml",
                    conf=float(s.get("confidence", 0.28)),
                    classes=self._active_classes(),
                    verbose=False,
                    imgsz=640 if s.get("performance_mode") != "Maximum Accuracy" else 768,
                )
                infer_ms = (time.perf_counter()-infer_start)*1000.0
                self.infer_ms_ema = infer_ms if self.infer_ms_ema <= 0 else .90*self.infer_ms_ema + .10*infer_ms

                annotated = enhanced.copy()
                detections: list[Detection] = []
                now = time.time()

                if results and results[0].boxes is not None and results[0].boxes.id is not None:
                    for box, tid_tensor in zip(results[0].boxes, results[0].boxes.id):
                        cls_id = int(box.cls.item())
                        if cls_id not in TARGET_CLASSES:
                            continue
                        tid = int(tid_tensor.item())
                        x1,y1,x2,y2 = [int(v) for v in box.xyxy[0].tolist()]
                        x1=max(0,min(x1,raw.shape[1]-1)); y1=max(0,min(y1,raw.shape[0]-1))
                        x2=max(0,min(x2,raw.shape[1])); y2=max(0,min(y2,raw.shape[0]))
                        if x2<=x1 or y2<=y1:
                            continue
                        category = CATEGORY_BY_CLASS[cls_id]
                        label = TARGET_CLASSES[cls_id]
                        center = ((x1+x2)//2,(y1+y2)//2)
                        zone = self.zones.zone_at(center, raw.shape)
                        if zone == "ignore":
                            continue
                        color = estimate_color(raw[y1:y2,x1:x2]) if category=="vehicle" else ""
                        det = Detection(
                            track_id=tid, class_id=cls_id, category=category, label=label,
                            confidence=float(box.conf.item()), xyxy=(x1,y1,x2,y2),
                            center=center, color=color, zone=zone
                        )
                        moving, score = self.motion.update(
                            tid, center, raw.shape, now,
                            float(s.get("motion_sensitivity",7.0)), category
                        )
                        det.is_moving = moving
                        det.motion_score = score
                        self.track_seen[tid] = self.track_seen.get(tid,0)+1
                        self.last_seen[tid] = now
                        self._update_best_crop(enhanced, det)

                        if category in {"vehicle","animal"} and (
                            (category=="vehicle" and moving and self.track_seen[tid]>=4) or
                            (category=="animal" and self.track_seen[tid]>=2)
                        ):
                            self._ensure_identity(enhanced, det)

                        if tid in self.track_identity:
                            det.persistent_id, det.display_name, det.persistent_match = self.track_identity[tid]

                        auto = self.speed.update(
                            det, now,
                            float(s.get("learning",{}).get("speed_scale",1.0)),
                            night_active,
                        )
                        if auto is not None and s.get("speed_mode","auto") == "auto":
                            self.speed_by_track[tid] = (auto[0], auto[1], "AUTO")
                        if tid in self.speed_by_track:
                            det.speed_mph, det.speed_confidence, det.speed_source = self.speed_by_track[tid]

                        detections.append(det)

                self.zones.draw(annotated)
                self._draw_tripwire(annotated)

                for det in detections:
                    self._process_event(enhanced, det)
                    self._draw_detection(annotated, det)

                if night_active and s.get("headlight_assist", True):
                    body_visible = any(d.category=="vehicle" and d.is_moving for d in detections)
                    box, hconf = self.headlights.detect(enhanced)
                    if box and hconf >= .72 and not body_visible:
                        x1,y1,x2,y2 = box
                        cv2.rectangle(annotated,(x1,y1),(x2,y2),(0,200,255),2)
                        cv2.putText(
                            annotated, f"PROBABLE VEHICLE / HEADLIGHTS {hconf:.0%}",
                            (x1,max(24,y1-8)), cv2.FONT_HERSHEY_SIMPLEX,.56,(0,200,255),2
                        )
                        if now-self.last_headlight_alert > 7:
                            self.last_headlight_alert = now
                            self.event_queue.put(("alert", {
                                "level":"notice",
                                "text":f"Night vehicle likely approaching — moving headlights {hconf:.0%}",
                                "speech":"Possible vehicle approaching at night."
                            }))

                self._forget_stale(now)
                dt = max(time.perf_counter()-loop_start,1e-6)
                fps=1.0/dt
                self.fps_ema = fps if self.fps_ema<=0 else .90*self.fps_ema + .10*fps
                if self.frame_count % 8 == 0:
                    self._publish_stats(detections, brightness, night_active, night_strength, quality)
                self._publish_frame(annotated)

        except Exception as exc:
            self.event_queue.put(("error", str(exc)))
        finally:
            try:
                if self.cap is not None:
                    self.cap.release()
            except Exception:
                pass
            self.cap = None
            self.running = False
            self.event_queue.put(("status", "Stopped"))

    def _publish_frame(self, frame):
        try:
            while True:
                self.frame_queue.get_nowait()
        except queue.Empty:
            pass
        try:
            self.frame_queue.put_nowait(frame)
        except queue.Full:
            pass

    def _publish_stats(self, detections, brightness, night_active, night_strength, quality):
        self.event_queue.put(("stats", {
            "fps": self.fps_ema,
            "infer_ms": self.infer_ms_ema,
            "brightness": brightness,
            "night_active": night_active,
            "night_strength": night_strength,
            "quality": quality,
            "vehicles": sum(d.category=="vehicle" and d.is_moving for d in detections),
            "people": sum(d.category=="person" for d in detections),
            "animals": sum(d.category=="animal" for d in detections),
        }))

    def _update_best_crop(self, frame, det: Detection):
        crop = crop_with_pad(frame, det.xyxy, .08)
        if crop.size == 0 or crop.shape[0]<20 or crop.shape[1]<20:
            return
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        sharp = float(cv2.Laplacian(gray,cv2.CV_64F).var())
        exposure=float(np.mean(gray))
        exposure_bonus=35.0 if 35<=exposure<=215 else 0.0
        size_bonus=min(220.0,(crop.shape[0]*crop.shape[1])/4500.0)
        score=sharp+exposure_bonus+size_bonus
        old=self.best_crop.get(det.track_id)
        if old is None or score>old[0]:
            self.best_crop[det.track_id]=(score,crop.copy())

    def _ensure_identity(self, frame, det: Detection):
        if det.track_id in self.track_identity:
            return
        crop = self.best_crop.get(det.track_id, (0,crop_with_pad(frame,det.xyxy,.06)))[1]
        fp = fingerprint(crop)
        if not fp:
            return
        threshold=.82
        best=None; best_score=0.0
        for row in self.db.identities(det.category, 350):
            score=fingerprint_similarity(
                fp,row["fingerprint"],det.color,row["color"],det.label,row["object_type"]
            )
            if score>best_score:
                best,best_score=row,score
        if best is not None and best_score>=threshold:
            self.db.touch_identity(best["code"])
            self.track_identity[det.track_id]=(best["code"],best["display_name"] or "",best_score)
            return

        stamp=int(time.time()*1000)
        temp=self.identity_dir/f"pending_{stamp}.jpg"
        if crop.size:
            cv2.imwrite(str(temp),crop)
        row=self.db.create_identity(det.category,det.label,det.color,fp,str(temp))
        final=self.identity_dir/f"{row['code']}.jpg"
        try:
            if temp.exists():
                temp.replace(final)
        except Exception:
            pass
        self.track_identity[det.track_id]=(row["code"],"",0.0)

    def _process_event(self, frame, det: Detection):
        tid=det.track_id
        s=self.settings.data

        if det.category=="person":
            if tid in self.person_logged or self.track_seen.get(tid,0)<3:
                return
            self.person_logged.add(tid)
            self._log_event(frame,det,"Entered view")
            self.event_queue.put(("alert", {
                "level":"person","text":f"Person detected • {det.zone or 'camera view'}",
                "speech":"Person detected."
            }))
            return

        if det.category=="animal":
            if tid in self.animal_logged or self.track_seen.get(tid,0)<3:
                return
            self.animal_logged.add(tid)
            self._log_event(frame,det,"Entered view")
            who=det.display_name or det.persistent_id or det.label
            self.event_queue.put(("alert", {
                "level":"animal","text":f"Animal detected • {who}",
                "speech":f"{who} detected."
            }))
            return

        # Vehicles: parked detections remain visible but never create traffic events.
        if not det.is_moving or tid in self.logged_tracks:
            return

        # Driveway activity is meaningful immediately after motion is confirmed.
        if det.zone=="driveway":
            self.logged_tracks.add(tid)
            self._log_event(frame,det,"Driveway movement")
            who=det.display_name or det.persistent_id or det.label
            self.event_queue.put(("alert", {
                "level":"vehicle","text":f"Driveway vehicle • {who}",
                "speech":"Vehicle in driveway."
            }))
            return

        # Otherwise log road traffic when the tracked center crosses the configured line.
        h,w=frame.shape[:2]
        orientation=s.get("tripwire_orientation","vertical")
        pct=float(s.get("tripwire_position",50))/100.0
        if orientation=="vertical":
            line=int(w*pct); coord=det.center[0]
            side=-1 if coord<line else 1
            neg_dir,pos_dir="Left → Right","Right → Left"
        else:
            line=int(h*pct); coord=det.center[1]
            side=-1 if coord<line else 1
            neg_dir,pos_dir="Top → Bottom","Bottom → Top"

        prev=self.previous_side.get(tid)
        self.previous_side[tid]=side
        if prev is None or prev==side:
            return

        direction=neg_dir if prev==-1 and side==1 else pos_dir
        self.logged_tracks.add(tid)
        self._log_event(frame,det,direction)
        who=det.display_name or det.persistent_id or det.label
        mph=f" • ~{det.speed_mph:.0f} MPH" if det.speed_mph else ""
        self.event_queue.put(("alert", {
            "level":"vehicle","text":f"Vehicle passed • {who}{mph}",
            "speech":f"Vehicle passed{f' at about {det.speed_mph:.0f} miles per hour' if det.speed_mph else ''}."
        }))

    def _log_event(self, frame, det: Detection, direction: str):
        stamp=datetime.now()
        path=self.snapshot_dir/f"{stamp:%Y%m%d_%H%M%S}_{det.category}_{det.track_id}.jpg"
        crop=self.best_crop.get(det.track_id,(0,crop_with_pad(frame,det.xyxy,.10)))[1]
        if crop.size:
            cv2.imwrite(str(path),crop)
        else:
            path=Path("")
        row=self.db.add_event(
            category=det.category,object_type=det.label,confidence=det.confidence,
            color=det.color,direction=direction,zone=det.zone,track_id=det.track_id,
            persistent_id=det.persistent_id,persistent_match=det.persistent_match,
            display_name=det.display_name,speed_mph=det.speed_mph,
            speed_source=det.speed_source,speed_confidence=det.speed_confidence,
            snapshot_path=str(path)
        )
        self.track_event_id[det.track_id]=int(row["id"])
        self.track_event_code[det.track_id]=row["event_code"]
        self.event_queue.put(("event",dict(row)))

    def _draw_tripwire(self, frame):
        s=self.settings.data
        h,w=frame.shape[:2]
        pct=float(s.get("tripwire_position",50))/100.0
        color=(0,225,255)
        if s.get("tripwire_orientation","vertical")=="vertical":
            x=int(w*pct); cv2.line(frame,(x,0),(x,h),color,2)
            cv2.putText(frame,"EVENT LINE",(min(x+8,w-150),28),cv2.FONT_HERSHEY_SIMPLEX,.55,color,2)
        else:
            y=int(h*pct); cv2.line(frame,(0,y),(w,y),color,2)
            cv2.putText(frame,"EVENT LINE",(10,max(22,y-8)),cv2.FONT_HERSHEY_SIMPLEX,.55,color,2)

    def _draw_detection(self, frame, det: Detection):
        x1,y1,x2,y2=det.xyxy
        if det.category=="vehicle":
            color=(45,200,90) if det.is_moving else (120,120,120)
            ident=det.display_name or det.persistent_id or f"Track {det.track_id}"
            state="MOVING" if det.is_moving else "STATIONARY"
            label=f"{ident} • {state} • {det.color} {det.label}"
            if det.speed_mph is not None and det.is_moving:
                label += f" • ~{det.speed_mph:.0f} MPH ({det.speed_confidence:.0%})"
        elif det.category=="person":
            color=(70,160,255); label=f"Person • {det.confidence:.0%}"
        else:
            color=(255,155,65); ident=det.display_name or det.persistent_id or det.label
            label=f"{ident} • {det.label} • {det.confidence:.0%}"
        if det.zone:
            label += f" • {det.zone.upper()}"
        cv2.rectangle(frame,(x1,y1),(x2,y2),color,2)
        (tw,th),_=cv2.getTextSize(label,cv2.FONT_HERSHEY_SIMPLEX,.50,2)
        yt=max(22,y1-7)
        cv2.rectangle(frame,(x1,yt-th-7),(min(frame.shape[1]-1,x1+tw+8),yt+3),(20,20,20),-1)
        cv2.putText(frame,label,(x1+4,yt),cv2.FONT_HERSHEY_SIMPLEX,.50,color,2)
        hist=self.motion.history.get(det.track_id)
        if hist and len(hist)>1:
            pts=[(int(x),int(y)) for _,x,y in hist]
            for a,b in zip(pts,pts[1:]):
                cv2.line(frame,a,b,color,2)

    def _forget_stale(self, now: float):
        stale=[tid for tid,ts in self.last_seen.items() if now-ts>20]
        for tid in stale:
            self.last_seen.pop(tid,None)
            self.track_seen.pop(tid,None)
            self.previous_center.pop(tid,None)
            self.previous_side.pop(tid,None)
            self.track_event_id.pop(tid,None)
            self.track_event_code.pop(tid,None)
            self.track_identity.pop(tid,None)
            self.best_crop.pop(tid,None)
            self.speed_by_track.pop(tid,None)
            self.logged_tracks.discard(tid)
            self.person_logged.discard(tid)
            self.animal_logged.discard(tid)
            self.motion.forget(tid)
            self.speed.forget(tid)
