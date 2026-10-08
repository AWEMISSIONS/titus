from __future__ import annotations

import json
from pathlib import Path


DEFAULT_SETTINGS = {
    "camera_source": "0",
    "confidence": 0.28,
    "motion_sensitivity": 7.0,
    "night_threshold": 78.0,
    "night_assist": True,
    "headlight_assist": True,
    "monitor_vehicles": True,
    "monitor_people": True,
    "monitor_animals": True,
    "voice_alerts": True,
    "sound_alerts": True,
    "tripwire_orientation": "vertical",
    "tripwire_position": 50,
    "speed_mode": "auto",
    "speed_gate_a": 35,
    "speed_gate_b": 65,
    "speed_distance_ft": 30.0,
    "retention_days": 30,
    "performance_mode": "Balanced",
    "auto_start_monitoring": False,
    "weather_enabled": True,
    "lightning_enabled": True,
    "weather_sample_seconds": 120,
    "lightning_clip_seconds": 5.0,
    "lightning_clip_fps": 15.0,
    "zones": {
        "road": None,
        "driveway": None,
        "sidewalk": None,
        "ignore": None
    },
    "learning": {
        "feedback_count": 0,
        "false_alarm_count": 0,
        "missed_count": 0,
        "speed_scale": 1.0,
    }
}


class SettingsStore:
    def __init__(self, path: Path):
        self.path = path
        self.data = json.loads(json.dumps(DEFAULT_SETTINGS))
        self.load()

    def load(self):
        if not self.path.exists():
            return
        try:
            incoming = json.loads(self.path.read_text(encoding="utf-8"))
            self._merge(self.data, incoming)
        except Exception:
            pass

    def _merge(self, base: dict, incoming: dict):
        for key, value in incoming.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._merge(base[key], value)
            else:
                base[key] = value

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def learn_false_alarm(self):
        l = self.data["learning"]
        l["feedback_count"] += 1
        l["false_alarm_count"] += 1
        self.data["motion_sensitivity"] = max(1.0, float(self.data["motion_sensitivity"]) - 0.25)
        self.data["confidence"] = min(0.65, float(self.data["confidence"]) + 0.01)
        self.save()

    def learn_missed(self):
        l = self.data["learning"]
        l["feedback_count"] += 1
        l["missed_count"] += 1
        self.data["motion_sensitivity"] = min(10.0, float(self.data["motion_sensitivity"]) + 0.30)
        self.data["confidence"] = max(0.15, float(self.data["confidence"]) - 0.01)
        self.save()
