from __future__ import annotations

import os
import queue
import sys
from pathlib import Path

import customtkinter as ctk

from database import TitusDatabase
from engine import TitusEngine
from settings import SettingsStore
from ui import TitusUI


if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parents[1]

os.chdir(APP_DIR)
DATA_DIR = APP_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
(DATA_DIR / "snapshots").mkdir(parents=True, exist_ok=True)
(DATA_DIR / "identities").mkdir(parents=True, exist_ok=True)


def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    settings = SettingsStore(DATA_DIR / "settings.json")
    db = TitusDatabase(DATA_DIR / "titus.db")
    frame_queue: queue.Queue = queue.Queue(maxsize=1)
    event_queue: queue.Queue = queue.Queue()
    engine = TitusEngine(APP_DIR, db, settings, frame_queue, event_queue)

    root = ctk.CTk()
    TitusUI(root, engine, db, settings, APP_DIR)
    root.mainloop()


if __name__ == "__main__":
    main()
