from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np


@dataclass
class WeatherState:
    condition: str
    confidence: float
    brightness: float
    cloud_score: float
    rain_score: float
    storm_active: bool


class SkyStormMonitor:
    """Camera-only local weather + lightning monitor.

    Weather labels are visual estimates. Lightning detection looks for a rapid,
    scene-wide illumination jump rather than a small local bright object such as
    a headlight. Clips use the camera's current native frame resolution.
    """

    def __init__(self, clip_dir: Path, snapshot_dir: Path, clip_seconds: float = 5.0, fps: float = 15.0):
        self.clip_dir = clip_dir
        self.snapshot_dir = snapshot_dir
        self.clip_dir.mkdir(parents=True, exist_ok=True)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

        self.clip_seconds = float(clip_seconds)
        self.pre_seconds = self.clip_seconds / 2.0
        self.post_seconds = self.clip_seconds / 2.0
        self.target_fps = float(fps)
        self.buffer: deque[tuple[float, bytes]] = deque()
        self.active_clips: list[dict] = []
        self.last_buffer_store = 0.0

        self.baseline_gray: Optional[np.ndarray] = None
        self.baseline_brightness: Optional[float] = None
        self.last_lightning = 0.0
        self.lightning_times: deque[float] = deque(maxlen=200)
        self.last_condition = "Unknown"
        self.condition_ema: dict[str, float] = {}
        self.last_state = WeatherState("Unknown", 0.0, 0.0, 0.0, 0.0, False)
        self.last_weather_calc = 0.0

        self.prev_gray: Optional[np.ndarray] = None
        self.rain_history: deque[float] = deque(maxlen=20)

    def reset(self):
        self.buffer.clear()
        self.active_clips.clear()
        self.last_buffer_store = 0.0
        self.baseline_gray = None
        self.baseline_brightness = None
        self.prev_gray = None
        self.rain_history.clear()
        self.last_weather_calc = 0.0

    def lightning_today(self) -> int:
        now = time.time()
        day_start = now - (now % 86400)
        return sum(ts >= day_start for ts in self.lightning_times)

    def recent_lightning_count(self, seconds: float = 1800.0) -> int:
        now = time.time()
        return sum(now - ts <= seconds for ts in self.lightning_times)

    def process(self, frame: np.ndarray, now: Optional[float] = None):
        now = now or time.time()
        completed = []

        self._buffer_frame(frame, now)
        # Weather classification is slower than flash detection; update the
        # label about once per second while checking lightning every frame.
        if now - self.last_weather_calc >= 0.75 or self.last_state.condition == "Unknown":
            state = self._estimate_weather(frame, now)
            self.last_weather_calc = now
        else:
            state = self.last_state
        strike = self._detect_lightning(frame, now, state)

        if strike is not None:
            self.lightning_times.append(now)
            self.last_lightning = now
            stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(now))
            clip_path = self.clip_dir / f"lightning_{stamp}_{int((now%1)*1000):03d}.mp4"
            snapshot_path = self.snapshot_dir / f"lightning_{stamp}_{int((now%1)*1000):03d}.jpg"
            cv2.imwrite(str(snapshot_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 97])
            frames = [(ts, data) for ts, data in self.buffer if ts >= now - self.pre_seconds]
            self.active_clips.append({
                "started": now,
                "end_at": now + self.post_seconds,
                "path": clip_path,
                "frames": frames,
                "size": (frame.shape[1], frame.shape[0]),
            })
            strike.update({
                "clip_path": str(clip_path),
                "snapshot_path": str(snapshot_path),
                "weather": state.condition,
            })

        # The current frame has already been put in the rolling buffer. Add it
        # to all active strike clips and finalize any whose post-roll is done.
        for item in list(self.active_clips):
            if item["frames"] and item["frames"][-1][0] < now:
                encoded = self._encode_jpeg(frame)
                if encoded is not None:
                    item["frames"].append((now, encoded))
            if now >= item["end_at"]:
                ok = self._write_clip(item)
                completed.append({
                    "clip_path": str(item["path"]),
                    "saved": bool(ok),
                })
                self.active_clips.remove(item)

        return state, strike, completed

    def _buffer_frame(self, frame: np.ndarray, now: float):
        # Preserve full camera resolution but cap buffering FPS to keep memory sane.
        if now - self.last_buffer_store < 1.0 / max(self.target_fps, 1.0):
            return
        self.last_buffer_store = now
        encoded = self._encode_jpeg(frame)
        if encoded is None:
            return
        self.buffer.append((now, encoded))
        cutoff = now - self.pre_seconds - 0.6
        while self.buffer and self.buffer[0][0] < cutoff:
            self.buffer.popleft()

    @staticmethod
    def _encode_jpeg(frame: np.ndarray) -> Optional[bytes]:
        ok, data = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        return data.tobytes() if ok else None

    def _write_clip(self, item: dict) -> bool:
        frames = item["frames"]
        if not frames:
            return False
        width, height = item["size"]
        writer = cv2.VideoWriter(
            str(item["path"]),
            cv2.VideoWriter_fourcc(*"mp4v"),
            self.target_fps,
            (int(width), int(height)),
        )
        if not writer.isOpened():
            return False
        try:
            for _ts, payload in frames:
                arr = np.frombuffer(payload, dtype=np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if frame is None:
                    continue
                if frame.shape[1] != width or frame.shape[0] != height:
                    frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_LINEAR)
                writer.write(frame)
        finally:
            writer.release()
        return item["path"].exists() and item["path"].stat().st_size > 0

    def _estimate_weather(self, frame: np.ndarray, now: float) -> WeatherState:
        h, w = frame.shape[:2]
        # Prefer the upper half where sky/clouds usually live, but keep some
        # whole-scene context in case the camera doesn't show much sky.
        sky = frame[: max(1, int(h * 0.52)), :]
        small = cv2.resize(sky, (320, 160), interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

        brightness = float(np.mean(gray))
        median_brightness = float(np.median(gray))
        saturation = float(np.mean(hsv[:, :, 1]))
        contrast = float(np.std(gray))

        # Cloud score favors low saturation, moderate brightness, and low contrast.
        cloud_score = (
            0.45 * (1.0 - min(1.0, saturation / 95.0))
            + 0.30 * (1.0 - min(1.0, contrast / 70.0))
            + 0.25 * (1.0 - min(1.0, abs(brightness - 135.0) / 135.0))
        )
        cloud_score = max(0.0, min(1.0, cloud_score))

        rain_score = self._estimate_rain(gray)
        recent_lightning = self.recent_lightning_count(1200.0)
        storm_active = recent_lightning > 0 or (rain_score > 0.66 and cloud_score > 0.58)

        if median_brightness < 38:
            condition = "Thunderstorm" if recent_lightning else "Night"
            confidence = 0.90 if median_brightness < 24 else 0.76
        elif storm_active:
            condition = "Thunderstorm"
            confidence = max(0.78, min(0.98, 0.72 + 0.06 * recent_lightning + 0.12 * rain_score))
        elif rain_score > 0.64:
            condition = "Rainy"
            confidence = min(0.92, 0.58 + rain_score * 0.42)
        elif cloud_score > 0.61:
            condition = "Cloudy"
            confidence = min(0.90, 0.48 + cloud_score * 0.48)
        else:
            # Stronger light + contrast generally corresponds to clearer/sunnier scenes.
            sunny_score = 0.55 * min(1.0, brightness / 175.0) + 0.45 * min(1.0, contrast / 65.0)
            condition = "Sunny"
            confidence = max(0.50, min(0.92, sunny_score))

        self.last_condition = condition
        state = WeatherState(
            condition=condition,
            confidence=float(confidence),
            brightness=brightness,
            cloud_score=cloud_score,
            rain_score=rain_score,
            storm_active=storm_active,
        )
        self.last_state = state
        return state

    def _estimate_rain(self, gray: np.ndarray) -> float:
        # Visual rain is hard with a single camera. This looks for thin,
        # near-vertical transient streaks and repeated fine motion. The score is
        # intentionally exposed as a confidence rather than treated as certainty.
        edges = cv2.Canny(gray, 45, 120)
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180.0, 22, minLineLength=7, maxLineGap=4)
        vertical = 0
        total = 0
        if lines is not None:
            for line in lines[:, 0]:
                x1, y1, x2, y2 = [int(v) for v in line]
                dx = abs(x2 - x1)
                dy = abs(y2 - y1)
                if dy < 5:
                    continue
                total += 1
                if dx / max(dy, 1) < 0.42:
                    vertical += 1

        streak_score = min(1.0, vertical / 28.0)
        motion_score = 0.0
        if self.prev_gray is not None:
            diff = cv2.absdiff(gray, self.prev_gray)
            # Fine motion rather than large moving objects.
            moving = np.mean((diff > 16).astype(np.float32))
            motion_score = min(1.0, moving / 0.12)
        self.prev_gray = gray.copy()

        raw = 0.62 * streak_score + 0.38 * motion_score
        self.rain_history.append(raw)
        return float(np.mean(self.rain_history)) if self.rain_history else raw

    def _detect_lightning(self, frame: np.ndarray, now: float, state: WeatherState):
        if now - self.last_lightning < 1.25:
            return None

        small = cv2.resize(frame, (320, 180), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32)
        current_median = float(np.median(gray))

        if self.baseline_gray is None:
            self.baseline_gray = gray.copy()
            self.baseline_brightness = current_median
            return None

        diff = gray - self.baseline_gray
        median_jump = float(np.median(diff))
        bright_fraction = float(np.mean(diff > 24.0))
        upper_fraction = float(np.mean(diff[:90, :] > 24.0))
        lower_fraction = float(np.mean(diff[90:, :] > 24.0))

        # Scene-wide flashes help distinguish lightning from local headlights.
        scene_wide = bright_fraction > 0.36 and upper_fraction > 0.28 and lower_fraction > 0.18
        strong_jump = median_jump > (23.0 if current_median < 90 else 30.0)

        # More conservative in bright daytime conditions.
        threshold_bonus = 0.0 if state.condition in {"Night", "Rainy", "Thunderstorm", "Cloudy"} else 8.0
        triggered = scene_wide and median_jump > (23.0 + threshold_bonus)

        # Update a slow baseline. During a suspected flash, do not immediately
        # absorb the flash into the baseline.
        alpha = 0.018 if triggered else 0.045
        self.baseline_gray = (1.0 - alpha) * self.baseline_gray + alpha * gray
        self.baseline_brightness = (
            current_median if self.baseline_brightness is None
            else (1.0 - alpha) * self.baseline_brightness + alpha * current_median
        )

        if not triggered:
            return None

        confidence = 0.55
        confidence += min(0.22, max(0.0, (median_jump - 23.0) / 90.0))
        confidence += min(0.18, bright_fraction * 0.25)
        if state.condition in {"Cloudy", "Rainy", "Thunderstorm", "Night"}:
            confidence += 0.08
        confidence = max(0.55, min(0.98, confidence))

        return {
            "confidence": confidence,
            "median_jump": median_jump,
            "bright_fraction": bright_fraction,
        }
