from __future__ import annotations

import csv
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional


class TitusDatabase:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        with self.conn:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_code TEXT UNIQUE,
                    happened_at TEXT NOT NULL,
                    category TEXT NOT NULL,
                    object_type TEXT NOT NULL,
                    color TEXT DEFAULT '',
                    direction TEXT DEFAULT '',
                    zone TEXT DEFAULT '',
                    confidence REAL NOT NULL,
                    track_id INTEGER,
                    persistent_id TEXT DEFAULT '',
                    persistent_match REAL DEFAULT 0,
                    display_name TEXT DEFAULT '',
                    speed_mph REAL,
                    speed_source TEXT DEFAULT '',
                    speed_confidence REAL DEFAULT 0,
                    snapshot_path TEXT DEFAULT '',
                    bookmarked INTEGER DEFAULT 0,
                    reviewed INTEGER DEFAULT 0,
                    note TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS identities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT UNIQUE,
                    category TEXT NOT NULL,
                    object_type TEXT NOT NULL,
                    color TEXT DEFAULT '',
                    fingerprint TEXT NOT NULL,
                    display_name TEXT DEFAULT '',
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    seen_count INTEGER NOT NULL DEFAULT 1,
                    snapshot_path TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    happened_at TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    event_code TEXT DEFAULT '',
                    note TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS weather_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    happened_at TEXT NOT NULL,
                    condition TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    brightness REAL NOT NULL,
                    cloud_score REAL NOT NULL,
                    rain_score REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS lightning_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strike_code TEXT UNIQUE,
                    happened_at TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    weather TEXT DEFAULT '',
                    clip_path TEXT DEFAULT '',
                    snapshot_path TEXT DEFAULT '',
                    clip_saved INTEGER DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_events_time ON events(happened_at DESC);
                CREATE INDEX IF NOT EXISTS idx_events_category_time ON events(category, happened_at DESC);
                CREATE INDEX IF NOT EXISTS idx_events_pid ON events(persistent_id);
                """
            )

    @staticmethod
    def _event_prefix(category: str) -> str:
        return {"vehicle": "V", "person": "P", "animal": "A"}.get(category, "E")

    def add_event(
        self,
        *,
        category: str,
        object_type: str,
        confidence: float,
        color: str = "",
        direction: str = "",
        zone: str = "",
        track_id: int | None = None,
        persistent_id: str = "",
        persistent_match: float = 0.0,
        display_name: str = "",
        speed_mph: float | None = None,
        speed_source: str = "",
        speed_confidence: float = 0.0,
        snapshot_path: str = "",
    ):
        now = datetime.now().isoformat(timespec="seconds")
        with self.lock, self.conn:
            cur = self.conn.execute(
                """
                INSERT INTO events (
                    event_code,happened_at,category,object_type,color,direction,zone,
                    confidence,track_id,persistent_id,persistent_match,display_name,
                    speed_mph,speed_source,speed_confidence,snapshot_path
                )
                VALUES (NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    now, category, object_type, color, direction, zone,
                    float(confidence), track_id, persistent_id, float(persistent_match),
                    display_name, speed_mph, speed_source, float(speed_confidence),
                    snapshot_path,
                ),
            )
            row_id = int(cur.lastrowid)
            event_code = f"{self._event_prefix(category)}-{row_id:06d}"
            self.conn.execute("UPDATE events SET event_code=? WHERE id=?", (event_code, row_id))
            return self.conn.execute("SELECT * FROM events WHERE id=?", (row_id,)).fetchone()

    def update_speed(self, event_id: int, mph: float, source: str, confidence: float):
        with self.lock, self.conn:
            self.conn.execute(
                "UPDATE events SET speed_mph=?,speed_source=?,speed_confidence=? WHERE id=?",
                (float(mph), source, float(confidence), int(event_id)),
            )

    def set_note(self, event_code: str, note: str) -> bool:
        with self.lock, self.conn:
            cur = self.conn.execute(
                "UPDATE events SET note=? WHERE event_code=?",
                (note.strip(), event_code.upper()),
            )
            return cur.rowcount > 0

    def set_display_name(self, event_code: str, name: str) -> bool:
        with self.lock, self.conn:
            cur = self.conn.execute(
                "UPDATE events SET display_name=? WHERE event_code=?",
                (name.strip(), event_code.upper()),
            )
            return cur.rowcount > 0

    def toggle_bookmark(self, event_code: str) -> Optional[bool]:
        with self.lock, self.conn:
            row = self.conn.execute(
                "SELECT bookmarked FROM events WHERE event_code=?", (event_code.upper(),)
            ).fetchone()
            if not row:
                return None
            newv = 0 if int(row["bookmarked"] or 0) else 1
            self.conn.execute(
                "UPDATE events SET bookmarked=? WHERE event_code=?",
                (newv, event_code.upper()),
            )
            return bool(newv)

    def mark_reviewed(self, event_code: str, reviewed: bool = True):
        with self.lock, self.conn:
            self.conn.execute(
                "UPDATE events SET reviewed=? WHERE event_code=?",
                (1 if reviewed else 0, event_code.upper()),
            )

    def get_event(self, event_code: str):
        with self.lock:
            return self.conn.execute(
                "SELECT * FROM events WHERE event_code=?", (event_code.upper(),)
            ).fetchone()

    def add_feedback(self, kind: str, event_code: str = "", note: str = ""):
        with self.lock, self.conn:
            self.conn.execute(
                "INSERT INTO feedback(happened_at,kind,event_code,note) VALUES(?,?,?,?)",
                (datetime.now().isoformat(timespec="seconds"), kind, event_code, note),
            )

    def add_weather_sample(
        self, condition: str, confidence: float, brightness: float,
        cloud_score: float, rain_score: float
    ):
        with self.lock, self.conn:
            self.conn.execute(
                """INSERT INTO weather_samples(
                    happened_at,condition,confidence,brightness,cloud_score,rain_score
                ) VALUES(?,?,?,?,?,?)""",
                (
                    datetime.now().isoformat(timespec="seconds"),
                    condition, float(confidence), float(brightness),
                    float(cloud_score), float(rain_score),
                ),
            )

    def add_lightning_event(
        self, confidence: float, weather: str, clip_path: str, snapshot_path: str
    ):
        now = datetime.now().isoformat(timespec="seconds")
        with self.lock, self.conn:
            cur = self.conn.execute(
                """INSERT INTO lightning_events(
                    strike_code,happened_at,confidence,weather,clip_path,snapshot_path,clip_saved
                ) VALUES(NULL,?,?,?,?,?,0)""",
                (now, float(confidence), weather, clip_path, snapshot_path),
            )
            row_id = int(cur.lastrowid)
            code = f"L-{row_id:05d}"
            self.conn.execute(
                "UPDATE lightning_events SET strike_code=? WHERE id=?",
                (code, row_id),
            )
            return self.conn.execute(
                "SELECT * FROM lightning_events WHERE id=?", (row_id,)
            ).fetchone()

    def mark_lightning_clip_saved(self, clip_path: str, saved: bool = True):
        with self.lock, self.conn:
            self.conn.execute(
                "UPDATE lightning_events SET clip_saved=? WHERE clip_path=?",
                (1 if saved else 0, clip_path),
            )

    def lightning_events(self, limit: int = 250):
        with self.lock:
            return self.conn.execute(
                "SELECT * FROM lightning_events ORDER BY id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()

    def lightning_stats_today(self) -> dict:
        today = datetime.now().date().isoformat()
        with self.lock:
            row = self.conn.execute(
                """SELECT COUNT(*) n,
                          AVG(confidence) avg_conf,
                          SUM(clip_saved=1) clips
                   FROM lightning_events
                   WHERE substr(happened_at,1,10)=?""",
                (today,),
            ).fetchone()
        return {
            "count": int(row["n"] or 0),
            "avg_confidence": float(row["avg_conf"] or 0.0),
            "clips": int(row["clips"] or 0),
        }

    def weather_summary_today(self) -> dict:
        today = datetime.now().date().isoformat()
        with self.lock:
            rows = self.conn.execute(
                """SELECT condition, COUNT(*) n, AVG(confidence) conf
                   FROM weather_samples
                   WHERE substr(happened_at,1,10)=?
                   GROUP BY condition
                   ORDER BY n DESC""",
                (today,),
            ).fetchall()
        counts = {str(r["condition"]): int(r["n"]) for r in rows}
        dominant = rows[0]["condition"] if rows else "Unknown"
        return {"dominant": dominant, "counts": counts}

    def create_identity(
        self, category: str, object_type: str, color: str,
        fingerprint: str, snapshot_path: str = ""
    ):
        prefix = "TV" if category == "vehicle" else "TA"
        now = datetime.now().isoformat(timespec="seconds")
        with self.lock, self.conn:
            cur = self.conn.execute(
                """
                INSERT INTO identities(
                    code,category,object_type,color,fingerprint,display_name,
                    first_seen,last_seen,seen_count,snapshot_path
                ) VALUES(NULL,?,?,?,?,?,?,?,1,?)
                """,
                (category, object_type, color, fingerprint, "", now, now, snapshot_path),
            )
            ident_id = int(cur.lastrowid)
            code = f"{prefix}-{ident_id:04d}"
            self.conn.execute("UPDATE identities SET code=? WHERE id=?", (code, ident_id))
            return self.conn.execute("SELECT * FROM identities WHERE id=?", (ident_id,)).fetchone()

    def touch_identity(self, code: str):
        with self.lock, self.conn:
            self.conn.execute(
                "UPDATE identities SET last_seen=?,seen_count=seen_count+1 WHERE code=?",
                (datetime.now().isoformat(timespec="seconds"), code),
            )

    def update_identity_snapshot(self, code: str, snapshot_path: str):
        with self.lock, self.conn:
            self.conn.execute(
                "UPDATE identities SET snapshot_path=? WHERE code=?",
                (snapshot_path, code.upper()),
            )

    def name_identity(self, code: str, name: str) -> bool:
        with self.lock, self.conn:
            cur = self.conn.execute(
                "UPDATE identities SET display_name=? WHERE code=?",
                (name.strip(), code.upper()),
            )
            return cur.rowcount > 0

    def identities(self, category: str | None = None, limit: int = 500):
        with self.lock:
            if category:
                return self.conn.execute(
                    "SELECT * FROM identities WHERE category=? ORDER BY last_seen DESC LIMIT ?",
                    (category, int(limit)),
                ).fetchall()
            return self.conn.execute(
                "SELECT * FROM identities ORDER BY last_seen DESC LIMIT ?", (int(limit),)
            ).fetchall()

    def recent_events(
        self,
        *,
        categories: Iterable[str] | None = None,
        query: str = "",
        zone: str = "",
        bookmarked_only: bool = False,
        reviewed: str = "all",
        limit: int = 500,
    ):
        clauses = ["1=1"]
        params: list[object] = []
        categories = tuple(categories or ())
        if categories:
            qmarks = ",".join("?" for _ in categories)
            clauses.append(f"category IN ({qmarks})")
            params.extend(categories)
        if query.strip():
            q = f"%{query.strip().lower()}%"
            clauses.append(
                """(
                    lower(event_code) LIKE ? OR lower(object_type) LIKE ? OR
                    lower(color) LIKE ? OR lower(direction) LIKE ? OR
                    lower(zone) LIKE ? OR lower(persistent_id) LIKE ? OR
                    lower(display_name) LIKE ? OR lower(note) LIKE ?
                )"""
            )
            params.extend([q] * 8)
        if zone:
            clauses.append("zone=?")
            params.append(zone)
        if bookmarked_only:
            clauses.append("bookmarked=1")
        if reviewed == "reviewed":
            clauses.append("reviewed=1")
        elif reviewed == "unreviewed":
            clauses.append("reviewed=0")

        params.append(int(limit))
        with self.lock:
            return self.conn.execute(
                f"""
                SELECT * FROM events
                WHERE {' AND '.join(clauses)}
                ORDER BY id DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()

    def stats_for_day(self, day: str | None = None) -> dict:
        day = day or datetime.now().date().isoformat()
        with self.lock:
            row = self.conn.execute(
                """
                SELECT
                  COUNT(*) total,
                  SUM(category='vehicle') vehicles,
                  SUM(category='person') people,
                  SUM(category='animal') animals,
                  SUM(zone='driveway') driveway,
                  SUM(bookmarked=1) bookmarked,
                  SUM(reviewed=0) unreviewed,
                  AVG(CASE WHEN category='vehicle' THEN speed_mph END) avg_speed,
                  MAX(CASE WHEN category='vehicle' THEN speed_mph END) max_speed,
                  COUNT(DISTINCT CASE WHEN category='vehicle' AND persistent_id<>'' THEN persistent_id END) unique_vehicles
                FROM events
                WHERE substr(happened_at,1,10)=?
                """,
                (day,),
            ).fetchone()
            repeats = self.conn.execute(
                """
                SELECT COUNT(*) n FROM (
                    SELECT persistent_id, COUNT(*) c
                    FROM events
                    WHERE category='vehicle' AND persistent_id<>'' AND substr(happened_at,1,10)=?
                    GROUP BY persistent_id
                    HAVING c>1
                )
                """,
                (day,),
            ).fetchone()["n"]
        return {
            "total": int(row["total"] or 0),
            "vehicles": int(row["vehicles"] or 0),
            "people": int(row["people"] or 0),
            "animals": int(row["animals"] or 0),
            "driveway": int(row["driveway"] or 0),
            "bookmarked": int(row["bookmarked"] or 0),
            "unreviewed": int(row["unreviewed"] or 0),
            "avg_speed": float(row["avg_speed"] or 0.0),
            "max_speed": float(row["max_speed"] or 0.0),
            "unique_vehicles": int(row["unique_vehicles"] or 0),
            "repeat_vehicles": int(repeats or 0),
        }

    def hourly_counts(self, day: str | None = None) -> list[int]:
        day = day or datetime.now().date().isoformat()
        result = [0] * 24
        with self.lock:
            rows = self.conn.execute(
                """
                SELECT CAST(substr(happened_at,12,2) AS INTEGER) hour, COUNT(*) n
                FROM events
                WHERE substr(happened_at,1,10)=?
                GROUP BY hour
                """,
                (day,),
            ).fetchall()
        for row in rows:
            hour = int(row["hour"])
            if 0 <= hour < 24:
                result[hour] = int(row["n"])
        return result

    def direction_counts(self, day: str | None = None) -> dict[str, int]:
        day = day or datetime.now().date().isoformat()
        with self.lock:
            rows = self.conn.execute(
                """
                SELECT direction,COUNT(*) n
                FROM events
                WHERE category='vehicle' AND substr(happened_at,1,10)=?
                GROUP BY direction
                """,
                (day,),
            ).fetchall()
        return {str(r["direction"] or "Unknown"): int(r["n"]) for r in rows}

    def top_repeat_vehicles(self, day: str | None = None, limit: int = 5):
        day = day or datetime.now().date().isoformat()
        with self.lock:
            return self.conn.execute(
                """
                SELECT persistent_id, MAX(display_name) display_name, COUNT(*) passes,
                       MAX(happened_at) last_seen
                FROM events
                WHERE category='vehicle' AND persistent_id<>'' AND substr(happened_at,1,10)=?
                GROUP BY persistent_id
                HAVING passes>1
                ORDER BY passes DESC, last_seen DESC
                LIMIT ?
                """,
                (day, int(limit)),
            ).fetchall()

    def busiest_hour(self, day: str | None = None) -> tuple[int, int]:
        hourly = self.hourly_counts(day)
        if not any(hourly):
            return 0, 0
        hour = max(range(24), key=lambda h: hourly[h])
        return hour, hourly[hour]

    def previous_day_stats(self) -> dict:
        day = (datetime.now().date() - timedelta(days=1)).isoformat()
        return self.stats_for_day(day)

    def export_csv(self, path: str):
        rows = self.recent_events(limit=100000)
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Event ID","Time","Category","Type","Color","Direction","Zone",
                "Confidence","Persistent ID","Repeat match","Name","Speed MPH",
                "Speed source","Speed confidence","Bookmarked","Reviewed","Note","Snapshot"
            ])
            for r in rows:
                writer.writerow([
                    r["event_code"], r["happened_at"], r["category"], r["object_type"],
                    r["color"], r["direction"], r["zone"], r["confidence"],
                    r["persistent_id"], r["persistent_match"], r["display_name"],
                    r["speed_mph"], r["speed_source"], r["speed_confidence"],
                    r["bookmarked"], r["reviewed"], r["note"], r["snapshot_path"],
                ])

    def close(self):
        with self.lock:
            self.conn.close()
