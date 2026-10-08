from __future__ import annotations

import os
import queue
import shutil
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
import customtkinter as ctk
from PIL import Image, ImageTk
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

try:
    import winsound
except Exception:
    winsound = None

try:
    import pyttsx3
except Exception:
    pyttsx3 = None


class SpeechWorker:
    def __init__(self):
        self.q: queue.Queue[str] = queue.Queue(maxsize=8)
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def say(self, text: str):
        if not text:
            return
        try:
            self.q.put_nowait(text)
        except queue.Full:
            pass

    def _run(self):
        engine = None
        if pyttsx3 is not None:
            try:
                engine = pyttsx3.init()
                engine.setProperty("rate", 185)
            except Exception:
                engine = None
        while self.running:
            try:
                text = self.q.get(timeout=.4)
            except queue.Empty:
                continue
            if engine is not None:
                try:
                    engine.say(text)
                    engine.runAndWait()
                    continue
                except Exception:
                    engine = None
            if winsound is not None:
                try:
                    winsound.MessageBeep()
                except Exception:
                    pass

    def stop(self):
        self.running = False


class TitusUI:
    def __init__(self, root, engine, db, settings, app_dir: Path):
        self.root = root
        self.engine = engine
        self.db = db
        self.settings = settings
        self.app_dir = app_dir
        self.frame_queue = engine.frame_queue
        self.event_queue = engine.event_queue
        self.speech = SpeechWorker()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        root.title("Titus — Local Vision Monitor")
        root.geometry("1540x920")
        root.minsize(1180, 720)
        root.protocol("WM_DELETE_WINDOW", self._close)
        root.bind("<F11>", lambda _e: self.toggle_fullscreen())
        root.bind("<Escape>", lambda _e: self.exit_fullscreen())

        self.current_view = "monitor"
        self.camera_photo = None
        self.latest_frame = None
        self.display_geometry = None
        self.fullscreen_window = None
        self.fullscreen_label = None
        self.fullscreen_photo = None
        self.zone_draw_mode = None
        self.zone_drag_start = None
        self.selected_event_code = ""
        self.selected_event_snapshot = ""
        self.alert_token = 0
        self.current_weather = {
            "condition": "Unknown", "confidence": 0.0, "rain_score": 0.0,
            "cloud_score": 0.0, "storm_active": False, "brightness": 0.0,
        }

        self._build_shell()
        self._build_monitor()
        self._build_events()
        self._build_insights()
        self._build_weather()
        self._build_settings()
        self._show_view("monitor")

        self._refresh_events()
        self._refresh_insights()
        self._refresh_monitor_cards()
        self.root.after(40, self._poll)
        self.root.after(350, self.engine.prepare_ai_async)

        if self.settings.data.get("auto_start_monitoring", False):
            self.root.after(700, self.start_monitoring)

    # ------------------------------------------------------------------
    # Shell / navigation
    # ------------------------------------------------------------------
    def _build_shell(self):
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(1, weight=1)

        self.sidebar = ctk.CTkFrame(self.root, width=205, corner_radius=0)
        self.sidebar.grid(row=0, column=0, rowspan=2, sticky="nsew")
        self.sidebar.grid_propagate(False)

        ctk.CTkLabel(
            self.sidebar, text="TITUS", font=ctk.CTkFont(size=30, weight="bold")
        ).pack(anchor="w", padx=22, pady=(25, 0))
        ctk.CTkLabel(
            self.sidebar, text="LOCAL VISION MONITOR", text_color="#8c9bad",
            font=ctk.CTkFont(size=11, weight="bold")
        ).pack(anchor="w", padx=22, pady=(0, 24))

        self.nav_buttons = {}
        for key, title in [
            ("monitor", "◉  Monitor"),
            ("events", "▤  Event Inbox"),
            ("insights", "▥  Insights"),
            ("weather", "☁  Sky & Storm"),
            ("settings", "⚙  Settings"),
        ]:
            b = ctk.CTkButton(
                self.sidebar, text=title, anchor="w", height=44, corner_radius=8,
                fg_color="transparent", hover_color="#213148",
                command=lambda k=key: self._show_view(k)
            )
            b.pack(fill="x", padx=12, pady=3)
            self.nav_buttons[key] = b

        ctk.CTkLabel(
            self.sidebar,
            text="LOCAL AI\nNo cloud video processing",
            justify="left", text_color="#66d19e",
            font=ctk.CTkFont(size=11, weight="bold")
        ).pack(side="bottom", anchor="w", padx=22, pady=22)

        self.topbar = ctk.CTkFrame(self.root, height=64, corner_radius=0)
        self.topbar.grid(row=0, column=1, sticky="ew")
        self.topbar.grid_propagate(False)
        self.topbar.grid_columnconfigure(1, weight=1)

        self.alert_dot = ctk.CTkLabel(self.topbar, text="●", text_color="#6d7a8a", font=ctk.CTkFont(size=20))
        self.alert_dot.grid(row=0, column=0, padx=(18, 8), pady=18)
        self.alert_label = ctk.CTkLabel(
            self.topbar, text="Titus ready", anchor="w",
            font=ctk.CTkFont(size=15, weight="bold")
        )
        self.alert_label.grid(row=0, column=1, sticky="ew")
        self.status_label = ctk.CTkLabel(self.topbar, text="Ready", text_color="#aeb9c5")
        self.status_label.grid(row=0, column=2, padx=18)

        self.content = ctk.CTkFrame(self.root, corner_radius=0, fg_color="#0d1117")
        self.content.grid(row=1, column=1, sticky="nsew")
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        self.views = {}

    def _show_view(self, name):
        self.current_view = name
        for key, frame in self.views.items():
            if key == name:
                frame.grid(row=0, column=0, sticky="nsew")
            else:
                frame.grid_forget()
        for key, btn in self.nav_buttons.items():
            btn.configure(fg_color="#1d4ed8" if key == name else "transparent")
        if name == "events":
            self._refresh_events()
        elif name == "insights":
            self._refresh_insights()
        elif name == "weather":
            self._refresh_weather_view()
        elif name == "monitor":
            self._refresh_monitor_cards()

    # ------------------------------------------------------------------
    # Monitor
    # ------------------------------------------------------------------
    def _build_monitor(self):
        frame = ctk.CTkFrame(self.content, fg_color="#0d1117")
        self.views["monitor"] = frame
        frame.grid_columnconfigure(0, weight=4)
        frame.grid_columnconfigure(1, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        controls = ctk.CTkFrame(frame, corner_radius=12)
        controls.grid(row=0, column=0, columnspan=2, sticky="ew", padx=16, pady=(16, 10))

        self.camera_var = ctk.StringVar(value=f"Camera {self.settings.data.get('camera_source','0')}")
        self.camera_menu = ctk.CTkComboBox(
            controls, variable=self.camera_var, width=170,
            values=["Camera 0","Camera 1","Camera 2","Camera 3","Camera 4"]
        )
        self.camera_menu.pack(side="left", padx=(12,6), pady=10)
        ctk.CTkButton(controls, text="Find Cameras", width=110, command=self.find_cameras).pack(side="left", padx=4)
        self.start_button = ctk.CTkButton(
            controls, text="Start Monitoring", fg_color="#15803d", hover_color="#166534",
            width=135, command=self.start_monitoring
        )
        self.start_button.pack(side="left", padx=4)
        ctk.CTkButton(controls, text="Stop", width=72, fg_color="#7f1d1d", hover_color="#991b1b",
                      command=self.stop_monitoring).pack(side="left", padx=4)
        ctk.CTkButton(controls, text="Fullscreen", width=95, command=self.toggle_fullscreen).pack(side="left", padx=4)
        ctk.CTkButton(controls, text="Snapshot", width=88, command=self.manual_snapshot).pack(side="left", padx=4)

        self.live_status = ctk.CTkLabel(controls, text="Camera idle", text_color="#9aa7b4")
        self.live_status.pack(side="right", padx=14)

        camera_card = ctk.CTkFrame(frame, corner_radius=14, fg_color="#080b10")
        camera_card.grid(row=1, column=0, sticky="nsew", padx=(16,8), pady=(0,16))
        camera_card.grid_rowconfigure(0, weight=1)
        camera_card.grid_columnconfigure(0, weight=1)

        self.video_label = ctk.CTkLabel(camera_card, text="Camera preview", fg_color="#080b10")
        self.video_label.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        self.video_label.bind("<Double-1>", lambda _e: self.toggle_fullscreen())
        self.video_label.bind("<ButtonPress-1>", self._zone_mouse_down)
        self.video_label.bind("<ButtonRelease-1>", self._zone_mouse_up)

        self.camera_footer = ctk.CTkFrame(camera_card, height=42, fg_color="#111722")
        self.camera_footer.grid(row=1, column=0, sticky="ew", padx=5, pady=(0,5))
        self.camera_footer.grid_columnconfigure(2, weight=1)
        self.live_objects_label = ctk.CTkLabel(self.camera_footer, text="0 moving vehicles • 0 people • 0 animals")
        self.live_objects_label.grid(row=0,column=0,padx=10,pady=8)
        self.ai_perf_label = ctk.CTkLabel(self.camera_footer, text="AI -- ms", text_color="#95a4b4")
        self.ai_perf_label.grid(row=0,column=1,padx=10)
        self.quality_label = ctk.CTkLabel(self.camera_footer, text="Camera quality --", text_color="#95a4b4")
        self.quality_label.grid(row=0,column=3,padx=10)

        right = ctk.CTkScrollableFrame(frame, corner_radius=14, width=310)
        right.grid(row=1,column=1,sticky="nsew",padx=(8,16),pady=(0,16))
        ctk.CTkLabel(right,text="TODAY",font=ctk.CTkFont(size=13,weight="bold"),text_color="#8da0b4").pack(anchor="w",pady=(4,8))

        self.today_cards = {}
        for key,title in [
            ("vehicles","Vehicles"),
            ("people","People"),
            ("animals","Animals"),
            ("driveway","Driveway events"),
            ("max_speed","Fastest est. speed"),
            ("weather","Sky / weather"),
            ("lightning","Lightning today"),
            ("unreviewed","Needs review"),
        ]:
            card=ctk.CTkFrame(right,corner_radius=10)
            card.pack(fill="x",pady=4)
            ctk.CTkLabel(card,text=title,text_color="#9ca9b7",font=ctk.CTkFont(size=11)).pack(anchor="w",padx=12,pady=(8,0))
            val=ctk.CTkLabel(card,text="0",font=ctk.CTkFont(size=24,weight="bold"))
            val.pack(anchor="w",padx=12,pady=(0,8))
            self.today_cards[key]=val

        ctk.CTkLabel(right,text="RECENT ACTIVITY",font=ctk.CTkFont(size=13,weight="bold"),text_color="#8da0b4").pack(anchor="w",pady=(16,8))
        self.recent_activity = ctk.CTkTextbox(right,height=180,wrap="word")
        self.recent_activity.pack(fill="x")
        self.recent_activity.configure(state="disabled")

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------
    def _build_events(self):
        frame=ctk.CTkFrame(self.content,fg_color="#0d1117")
        self.views["events"]=frame
        frame.grid_rowconfigure(1,weight=1)
        frame.grid_columnconfigure(0,weight=1)

        header=ctk.CTkFrame(frame,corner_radius=12)
        header.grid(row=0,column=0,sticky="ew",padx=16,pady=(16,10))
        self.search_var=ctk.StringVar()
        search=ctk.CTkEntry(header,textvariable=self.search_var,placeholder_text="Search ID, color, type, zone, name or note...",width=360)
        search.pack(side="left",padx=(12,6),pady=10)
        search.bind("<Return>",lambda _e:self._refresh_events())
        self.category_filter=ctk.StringVar(value="All")
        ctk.CTkComboBox(header,variable=self.category_filter,values=["All","Vehicles","People","Animals"],width=120,
                        command=lambda _v:self._refresh_events()).pack(side="left",padx=5)
        self.zone_filter=ctk.StringVar(value="All zones")
        ctk.CTkComboBox(header,variable=self.zone_filter,values=["All zones","road","driveway","sidewalk"],width=120,
                        command=lambda _v:self._refresh_events()).pack(side="left",padx=5)
        self.bookmark_only=ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(header,text="Bookmarked",variable=self.bookmark_only,command=self._refresh_events).pack(side="left",padx=8)
        ctk.CTkButton(header,text="Refresh",width=80,command=self._refresh_events).pack(side="left",padx=5)
        ctk.CTkButton(header,text="Export CSV",width=90,command=self.export_csv).pack(side="right",padx=12)

        body=ctk.CTkFrame(frame,fg_color="#0d1117")
        body.grid(row=1,column=0,sticky="nsew",padx=16,pady=(0,16))
        body.grid_columnconfigure(0,weight=2)
        body.grid_columnconfigure(1,weight=1)
        body.grid_rowconfigure(0,weight=1)

        self.event_list=ctk.CTkScrollableFrame(body,corner_radius=12)
        self.event_list.grid(row=0,column=0,sticky="nsew",padx=(0,8))

        detail=ctk.CTkFrame(body,corner_radius=12)
        detail.grid(row=0,column=1,sticky="nsew",padx=(8,0))
        self.detail_image=ctk.CTkLabel(detail,text="Select an event",height=260)
        self.detail_image.pack(fill="x",padx=12,pady=(12,8))
        self.detail_title=ctk.CTkLabel(detail,text="No event selected",font=ctk.CTkFont(size=18,weight="bold"),anchor="w")
        self.detail_title.pack(fill="x",padx=12,pady=(6,2))
        self.detail_text=ctk.CTkLabel(detail,text="",justify="left",anchor="nw",wraplength=360)
        self.detail_text.pack(fill="x",padx=12,pady=6)
        actions=ctk.CTkFrame(detail,fg_color="transparent")
        actions.pack(fill="x",padx=10,pady=8)
        ctk.CTkButton(actions,text="Open photo",width=90,command=self.open_selected_photo).pack(side="left",padx=3)
        ctk.CTkButton(actions,text="★ Bookmark",width=90,command=self.bookmark_selected).pack(side="left",padx=3)
        ctk.CTkButton(actions,text="Add note",width=80,command=self.note_selected).pack(side="left",padx=3)
        ctk.CTkButton(actions,text="Name / label",width=90,command=self.name_selected).pack(side="left",padx=3)
        ctk.CTkButton(detail,text="Mark reviewed",command=self.mark_selected_reviewed).pack(fill="x",padx=12,pady=(0,12))

    def _refresh_events(self):
        if not hasattr(self,"event_list"):
            return
        for child in self.event_list.winfo_children():
            child.destroy()
        cats=()
        cv=self.category_filter.get()
        if cv=="Vehicles": cats=("vehicle",)
        elif cv=="People": cats=("person",)
        elif cv=="Animals": cats=("animal",)
        zone="" if self.zone_filter.get()=="All zones" else self.zone_filter.get()
        rows=self.db.recent_events(
            categories=cats,query=self.search_var.get(),zone=zone,
            bookmarked_only=bool(self.bookmark_only.get()),limit=250
        )
        for row in rows:
            self._event_row(row)

    def _event_row(self,row):
        wrap=ctk.CTkFrame(self.event_list,corner_radius=10)
        wrap.pack(fill="x",pady=4,padx=2)
        icon={"vehicle":"🚗","person":"👤","animal":"🐾"}.get(row["category"],"•")
        left=ctk.CTkLabel(wrap,text=icon,font=ctk.CTkFont(size=22),width=36)
        left.pack(side="left",padx=(8,4),pady=10)
        title=row["display_name"] or row["persistent_id"] or row["event_code"]
        line1=ctk.CTkLabel(wrap,text=title,font=ctk.CTkFont(size=13,weight="bold"),anchor="w")
        line1.pack(anchor="w",padx=4,pady=(8,0))
        t=row["happened_at"].replace("T"," ")
        extra=f"{row['object_type']} {row['color'] or ''} • {row['zone'] or 'view'}"
        if row["speed_mph"]:
            extra += f" • ~{row['speed_mph']:.0f} MPH"
        line2=ctk.CTkLabel(wrap,text=f"{t}  |  {extra}",text_color="#9ba8b5",anchor="w")
        line2.pack(anchor="w",padx=4,pady=(0,8))
        if row["bookmarked"]:
            ctk.CTkLabel(wrap,text="★",text_color="#f5c451").pack(side="right",padx=8)
        for widget in (wrap,left,line1,line2):
            widget.bind("<Button-1>",lambda _e,r=dict(row):self.select_event(r))

    def select_event(self,row):
        self.selected_event_code=row["event_code"]
        self.selected_event_snapshot=row["snapshot_path"] or ""
        title=row["display_name"] or row["persistent_id"] or row["event_code"]
        self.detail_title.configure(text=title)
        lines=[
            f"Event: {row['event_code']}",
            f"Time: {row['happened_at'].replace('T',' ')}",
            f"Type: {row['category'].title()} / {row['object_type']}",
            f"Color: {row['color'] or '—'}",
            f"Direction: {row['direction'] or '—'}",
            f"Zone: {row['zone'] or 'Camera view'}",
            f"AI confidence: {row['confidence']:.0%}",
        ]
        if row["speed_mph"]:
            lines.append(f"Estimated speed: {row['speed_mph']:.1f} MPH ({row['speed_confidence']:.0%})")
        if row["persistent_match"]:
            lines.append(f"Repeat match: {row['persistent_match']:.0%}")
        if row["note"]:
            lines.append(f"Note: {row['note']}")
        self.detail_text.configure(text="\n".join(lines))
        self._load_detail_image(self.selected_event_snapshot)

    def _load_detail_image(self,path):
        if path and Path(path).exists():
            try:
                img=Image.open(path)
                img.thumbnail((360,260))
                photo=ctk.CTkImage(light_image=img,dark_image=img,size=img.size)
                self.detail_image.configure(image=photo,text="")
                self.detail_image.image=photo
                return
            except Exception:
                pass
        self.detail_image.configure(image=None,text="No snapshot")

    # ------------------------------------------------------------------
    # Insights
    # ------------------------------------------------------------------
    def _build_insights(self):
        frame=ctk.CTkScrollableFrame(self.content,fg_color="#0d1117")
        self.views["insights"]=frame

        ctk.CTkLabel(frame,text="Today at a glance",font=ctk.CTkFont(size=25,weight="bold")).pack(anchor="w",padx=16,pady=(16,8))
        self.insight_cards_frame=ctk.CTkFrame(frame,fg_color="transparent")
        self.insight_cards_frame.pack(fill="x",padx=12)
        self.insight_values={}
        for key,title in [
            ("vehicles","Vehicles"),("people","People"),("animals","Animals"),
            ("avg_speed","Avg. est. speed"),("max_speed","Fastest est. speed"),
            ("unique_vehicles","Unique likely vehicles")
        ]:
            card=ctk.CTkFrame(self.insight_cards_frame,corner_radius=12)
            card.pack(side="left",fill="x",expand=True,padx=4,pady=4)
            ctk.CTkLabel(card,text=title,text_color="#9aa7b4",font=ctk.CTkFont(size=11)).pack(pady=(10,2))
            val=ctk.CTkLabel(card,text="0",font=ctk.CTkFont(size=24,weight="bold"))
            val.pack(pady=(0,10))
            self.insight_values[key]=val

        lower=ctk.CTkFrame(frame,fg_color="transparent")
        lower.pack(fill="x",padx=16,pady=12)
        left=ctk.CTkFrame(lower,corner_radius=12)
        left.pack(side="left",fill="both",expand=True,padx=(0,6))
        right=ctk.CTkFrame(lower,corner_radius=12)
        right.pack(side="left",fill="both",expand=True,padx=(6,0))

        ctk.CTkLabel(left,text="Hourly activity",font=ctk.CTkFont(size=16,weight="bold")).pack(anchor="w",padx=12,pady=(12,4))
        self.hourly_canvas=tk.Canvas(left,height=250,bg="#151b24",highlightthickness=0)
        self.hourly_canvas.pack(fill="x",padx=12,pady=(0,12))

        ctk.CTkLabel(right,text="Titus daily brief",font=ctk.CTkFont(size=16,weight="bold")).pack(anchor="w",padx=12,pady=(12,4))
        self.daily_brief=ctk.CTkTextbox(right,height=250,wrap="word")
        self.daily_brief.pack(fill="both",expand=True,padx=12,pady=(0,12))
        self.daily_brief.configure(state="disabled")

        ctk.CTkButton(frame,text="Refresh insights",command=self._refresh_insights).pack(anchor="w",padx=16,pady=(0,20))

    def _refresh_insights(self):
        if not hasattr(self,"insight_values"):
            return
        s=self.db.stats_for_day()
        vals={
            "vehicles":str(s["vehicles"]),"people":str(s["people"]),"animals":str(s["animals"]),
            "avg_speed":f"{s['avg_speed']:.0f} mph" if s["avg_speed"] else "—",
            "max_speed":f"{s['max_speed']:.0f} mph" if s["max_speed"] else "—",
            "unique_vehicles":str(s["unique_vehicles"]),
        }
        for k,v in vals.items():
            self.insight_values[k].configure(text=v)
        self._draw_hourly(self.db.hourly_counts())
        brief=self._daily_brief_text(s)
        self.daily_brief.configure(state="normal")
        self.daily_brief.delete("1.0","end")
        self.daily_brief.insert("1.0",brief)
        self.daily_brief.configure(state="disabled")

    def _draw_hourly(self,counts):
        c=self.hourly_canvas
        c.delete("all")
        self.root.update_idletasks()
        w=max(c.winfo_width(),500); h=250
        maxv=max(counts) if any(counts) else 1
        left=28; bottom=h-28; usable=w-left-12
        barw=usable/24
        for hr,val in enumerate(counts):
            x1=left+hr*barw+1; x2=left+(hr+1)*barw-1
            bh=(val/maxv)*(h-58)
            c.create_rectangle(x1,bottom-bh,x2,bottom,fill="#2563eb",outline="")
            if hr%3==0:
                label="12a" if hr==0 else ("12p" if hr==12 else (f"{hr}a" if hr<12 else f"{hr-12}p"))
                c.create_text((x1+x2)/2,bottom+12,text=label,fill="#8fa0b3",font=("Segoe UI",8))
        c.create_line(left,bottom,w-10,bottom,fill="#344052")

    def _daily_brief_text(self,s):
        hour,count=self.db.busiest_hour()
        prev=self.db.previous_day_stats()
        repeat=self.db.top_repeat_vehicles(limit=3)
        parts=[]
        if s["total"]==0:
            return "No events have been logged today yet. Once Titus starts recording activity, this panel will summarize the day automatically."
        parts.append(f"Titus logged {s['vehicles']} vehicles, {s['people']} people, and {s['animals']} animals today.")
        if count:
            hour_text=datetime.strptime(str(hour),"%H").strftime("%-I %p") if os.name!="nt" else datetime.strptime(str(hour),"%H").strftime("%I %p").lstrip("0")
            parts.append(f"The busiest hour so far started around {hour_text}, with {count} events.")
        if s["driveway"]:
            parts.append(f"There have been {s['driveway']} events in the driveway zone.")
        if s["max_speed"]:
            parts.append(f"The fastest camera-estimated vehicle was about {s['max_speed']:.0f} MPH; uncalibrated camera speeds should be treated as estimates.")
        if repeat:
            names=[]
            for r in repeat:
                names.append(f"{r['display_name'] or r['persistent_id']} ({r['passes']} passes)")
            parts.append("Most repeated likely vehicles: "+", ".join(names)+".")
        if prev["total"]:
            change=s["total"]-prev["total"]
            if change>0:
                parts.append(f"Activity is {change} events higher than yesterday's full-day total so far.")
            elif change<0:
                parts.append(f"Activity is currently {abs(change)} events below yesterday's full-day total.")
        weather=self.db.weather_summary_today()
        lightning=self.db.lightning_stats_today()
        if weather["dominant"]!="Unknown":
            parts.append(f"The camera's dominant visual weather estimate today is {weather['dominant'].lower()}.")
        if lightning["count"]:
            parts.append(f"Titus detected {lightning['count']} likely lightning strike{'s' if lightning['count']!=1 else ''} today and saved {lightning['clips']} completed strike clip{'s' if lightning['clips']!=1 else ''}.")
        if s["unreviewed"]:
            parts.append(f"{s['unreviewed']} events have not been marked reviewed.")
        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Sky & Storm
    # ------------------------------------------------------------------
    def _build_weather(self):
        frame=ctk.CTkScrollableFrame(self.content,fg_color="#0d1117")
        self.views["weather"]=frame

        ctk.CTkLabel(frame,text="Sky & Storm",font=ctk.CTkFont(size=25,weight="bold")).pack(anchor="w",padx=16,pady=(16,4))
        ctk.CTkLabel(
            frame,
            text=("Titus estimates visible conditions from the camera. Sunny / cloudy / rainy are camera-based estimates, "
                  "so rain confidence can be lower if the lens cannot see sky or falling rain clearly."),
            text_color="#9aa7b4",wraplength=980,justify="left"
        ).pack(anchor="w",padx=16,pady=(0,12))

        cards=ctk.CTkFrame(frame,fg_color="transparent")
        cards.pack(fill="x",padx=12)
        self.weather_cards={}
        for key,title in [
            ("condition","Current condition"),("confidence","Weather confidence"),
            ("rain","Rain signal"),("lightning","Lightning today"),
            ("storm","Storm status"),("clips","Saved strike clips")
        ]:
            card=ctk.CTkFrame(cards,corner_radius=12)
            card.pack(side="left",fill="x",expand=True,padx=4,pady=4)
            ctk.CTkLabel(card,text=title,text_color="#9aa7b4",font=ctk.CTkFont(size=11)).pack(pady=(10,2))
            val=ctk.CTkLabel(card,text="—",font=ctk.CTkFont(size=21,weight="bold"))
            val.pack(pady=(0,10))
            self.weather_cards[key]=val

        info=ctk.CTkFrame(frame,corner_radius=12)
        info.pack(fill="x",padx=16,pady=10)
        ctk.CTkLabel(info,text="Lightning capture",font=ctk.CTkFont(size=16,weight="bold")).pack(anchor="w",padx=12,pady=(12,4))
        ctk.CTkLabel(
            info,
            text=("When Titus detects a scene-wide lightning flash, it counts the strike, saves a high-quality still, "
                  "and stores a 5-second video clip using the full resolution of the active camera feed. "
                  "The clip includes video from just before and just after the flash."),
            text_color="#a8b4c2",wraplength=1050,justify="left"
        ).pack(anchor="w",padx=12,pady=(0,12))

        ctk.CTkLabel(frame,text="Lightning history",font=ctk.CTkFont(size=18,weight="bold")).pack(anchor="w",padx=16,pady=(8,6))
        self.lightning_list=ctk.CTkScrollableFrame(frame,height=330,corner_radius=12)
        self.lightning_list.pack(fill="both",expand=True,padx=16,pady=(0,12))
        ctk.CTkButton(frame,text="Open lightning folder",command=self.open_lightning_folder).pack(anchor="w",padx=16,pady=(0,20))

    def _refresh_weather_view(self):
        if not hasattr(self,"weather_cards"):
            return
        ls=self.db.lightning_stats_today()
        state=self.current_weather
        self.weather_cards["condition"].configure(text=str(state.get("condition","Unknown")))
        self.weather_cards["confidence"].configure(text=f"{float(state.get('confidence',0)):.0%}")
        self.weather_cards["rain"].configure(text=f"{float(state.get('rain_score',0)):.0%}")
        self.weather_cards["lightning"].configure(text=str(ls["count"]))
        self.weather_cards["storm"].configure(text="ACTIVE" if state.get("storm_active") else "No")
        self.weather_cards["clips"].configure(text=str(ls["clips"]))

        for child in self.lightning_list.winfo_children():
            child.destroy()
        rows=self.db.lightning_events(200)
        if not rows:
            ctk.CTkLabel(self.lightning_list,text="No lightning strikes recorded yet.",text_color="#9aa7b4").pack(anchor="w",padx=8,pady=10)
            return
        for row in rows:
            box=ctk.CTkFrame(self.lightning_list,corner_radius=9)
            box.pack(fill="x",padx=3,pady=4)
            title=f"⚡ {row['strike_code']}   {row['happened_at'].replace('T',' ')}"
            ctk.CTkLabel(box,text=title,font=ctk.CTkFont(size=13,weight="bold")).pack(side="left",padx=10,pady=10)
            ctk.CTkLabel(
                box,text=f"{row['weather'] or 'Unknown'} • {row['confidence']:.0%}",
                text_color="#9aa7b4"
            ).pack(side="left",padx=6)
            if row["clip_saved"] and row["clip_path"] and Path(row["clip_path"]).exists():
                ctk.CTkButton(
                    box,text="Play 5-sec clip",width=110,
                    command=lambda p=row["clip_path"]:os.startfile(p)
                ).pack(side="right",padx=5,pady=7)
            if row["snapshot_path"] and Path(row["snapshot_path"]).exists():
                ctk.CTkButton(
                    box,text="Photo",width=65,fg_color="#374151",
                    command=lambda p=row["snapshot_path"]:os.startfile(p)
                ).pack(side="right",padx=5,pady=7)

    def open_lightning_folder(self):
        folder=self.app_dir/"data"/"lightning"
        folder.mkdir(parents=True,exist_ok=True)
        os.startfile(str(folder))

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------
    def _build_settings(self):
        frame=ctk.CTkScrollableFrame(self.content,fg_color="#0d1117")
        self.views["settings"]=frame
        s=self.settings.data

        ctk.CTkLabel(frame,text="Monitoring settings",font=ctk.CTkFont(size=25,weight="bold")).pack(anchor="w",padx=16,pady=(16,10))

        general=ctk.CTkFrame(frame,corner_radius=12)
        general.pack(fill="x",padx=16,pady=6)
        self.conf_var=ctk.DoubleVar(value=float(s.get("confidence",.28)))
        self.motion_var=ctk.DoubleVar(value=float(s.get("motion_sensitivity",7)))
        self.night_var=ctk.BooleanVar(value=bool(s.get("night_assist",True)))
        self.headlight_var=ctk.BooleanVar(value=bool(s.get("headlight_assist",True)))
        self.vehicle_var=ctk.BooleanVar(value=bool(s.get("monitor_vehicles",True)))
        self.people_var=ctk.BooleanVar(value=bool(s.get("monitor_people",True)))
        self.animal_var=ctk.BooleanVar(value=bool(s.get("monitor_animals",True)))
        self.voice_var=ctk.BooleanVar(value=bool(s.get("voice_alerts",True)))
        self.sound_var=ctk.BooleanVar(value=bool(s.get("sound_alerts",True)))
        self.orientation_var=ctk.StringVar(value=str(s.get("tripwire_orientation","vertical")))
        self.tripwire_var=ctk.DoubleVar(value=float(s.get("tripwire_position",50)))
        self.speed_mode_var=ctk.StringVar(value=str(s.get("speed_mode","auto")))
        self.speed_a_var=ctk.DoubleVar(value=float(s.get("speed_gate_a",35)))
        self.speed_b_var=ctk.DoubleVar(value=float(s.get("speed_gate_b",65)))
        self.speed_distance_var=ctk.DoubleVar(value=float(s.get("speed_distance_ft",30.0)))
        self.night_threshold_var=ctk.DoubleVar(value=float(s.get("night_threshold",78)))
        self.performance_var=ctk.StringVar(value=str(s.get("performance_mode","Balanced")))
        self.auto_start_var=ctk.BooleanVar(value=bool(s.get("auto_start_monitoring",False)))
        self.weather_enabled_var=ctk.BooleanVar(value=bool(s.get("weather_enabled",True)))
        self.lightning_enabled_var=ctk.BooleanVar(value=bool(s.get("lightning_enabled",True)))

        ctk.CTkLabel(general,text="Detection",font=ctk.CTkFont(size=16,weight="bold")).grid(row=0,column=0,columnspan=4,sticky="w",padx=12,pady=(12,6))
        ctk.CTkCheckBox(general,text="Vehicles",variable=self.vehicle_var).grid(row=1,column=0,sticky="w",padx=12,pady=5)
        ctk.CTkCheckBox(general,text="People",variable=self.people_var).grid(row=1,column=1,sticky="w",padx=12,pady=5)
        ctk.CTkCheckBox(general,text="Animals",variable=self.animal_var).grid(row=1,column=2,sticky="w",padx=12,pady=5)
        ctk.CTkCheckBox(general,text="Voice alerts",variable=self.voice_var).grid(row=2,column=0,sticky="w",padx=12,pady=5)
        ctk.CTkCheckBox(general,text="Sound alerts",variable=self.sound_var).grid(row=2,column=1,sticky="w",padx=12,pady=5)
        ctk.CTkCheckBox(general,text="Night Assist",variable=self.night_var).grid(row=2,column=2,sticky="w",padx=12,pady=5)
        ctk.CTkCheckBox(general,text="Headlight assist",variable=self.headlight_var).grid(row=2,column=3,sticky="w",padx=12,pady=5)

        ctk.CTkLabel(general,text="AI confidence").grid(row=3,column=0,sticky="w",padx=12,pady=(10,0))
        ctk.CTkSlider(general,from_=0.15,to=.70,variable=self.conf_var,width=240).grid(row=4,column=0,columnspan=2,sticky="w",padx=12,pady=(0,12))
        ctk.CTkLabel(general,text="Motion sensitivity").grid(row=3,column=2,sticky="w",padx=12,pady=(10,0))
        ctk.CTkSlider(general,from_=1,to=10,variable=self.motion_var,width=240).grid(row=4,column=2,columnspan=2,sticky="w",padx=12,pady=(0,12))

        tracking=ctk.CTkFrame(frame,corner_radius=12)
        tracking.pack(fill="x",padx=16,pady=6)
        ctk.CTkLabel(tracking,text="Tracking, event line & speed",font=ctk.CTkFont(size=16,weight="bold")).grid(row=0,column=0,columnspan=5,sticky="w",padx=12,pady=(12,8))
        ctk.CTkLabel(tracking,text="Traffic direction").grid(row=1,column=0,sticky="w",padx=12,pady=4)
        ctk.CTkSegmentedButton(tracking,values=["vertical","horizontal"],variable=self.orientation_var).grid(row=1,column=1,sticky="w",padx=8,pady=4)
        ctk.CTkLabel(tracking,text="Event line position").grid(row=1,column=2,sticky="w",padx=12,pady=4)
        ctk.CTkSlider(tracking,from_=10,to=90,variable=self.tripwire_var,width=210).grid(row=1,column=3,sticky="w",padx=8,pady=4)

        ctk.CTkLabel(tracking,text="Speed mode").grid(row=2,column=0,sticky="w",padx=12,pady=4)
        ctk.CTkSegmentedButton(tracking,values=["auto","calibrated"],variable=self.speed_mode_var).grid(row=2,column=1,sticky="w",padx=8,pady=4)
        ctk.CTkLabel(tracking,text="Gate A").grid(row=2,column=2,sticky="w",padx=12,pady=4)
        ctk.CTkSlider(tracking,from_=5,to=95,variable=self.speed_a_var,width=210).grid(row=2,column=3,sticky="w",padx=8,pady=4)
        ctk.CTkLabel(tracking,text="Gate B").grid(row=3,column=2,sticky="w",padx=12,pady=4)
        ctk.CTkSlider(tracking,from_=5,to=95,variable=self.speed_b_var,width=210).grid(row=3,column=3,sticky="w",padx=8,pady=4)
        ctk.CTkLabel(tracking,text="Actual A↔B feet").grid(row=3,column=0,sticky="w",padx=12,pady=4)
        ctk.CTkEntry(tracking,textvariable=self.speed_distance_var,width=100).grid(row=3,column=1,sticky="w",padx=8,pady=4)

        ctk.CTkLabel(tracking,text="Night threshold").grid(row=4,column=0,sticky="w",padx=12,pady=4)
        ctk.CTkSlider(tracking,from_=35,to=130,variable=self.night_threshold_var,width=210).grid(row=4,column=1,sticky="w",padx=8,pady=4)
        ctk.CTkLabel(tracking,text="Performance").grid(row=4,column=2,sticky="w",padx=12,pady=4)
        ctk.CTkComboBox(tracking,values=["Fast","Balanced","Maximum Accuracy"],variable=self.performance_var,width=180).grid(row=4,column=3,sticky="w",padx=8,pady=4)
        ctk.CTkCheckBox(tracking,text="Start monitoring when Titus opens",variable=self.auto_start_var).grid(row=5,column=0,columnspan=3,sticky="w",padx=12,pady=(6,12))

        skysettings=ctk.CTkFrame(frame,corner_radius=12)
        skysettings.pack(fill="x",padx=16,pady=6)
        ctk.CTkLabel(skysettings,text="Sky & Storm",font=ctk.CTkFont(size=16,weight="bold")).pack(anchor="w",padx=12,pady=(12,6))
        row=ctk.CTkFrame(skysettings,fg_color="transparent")
        row.pack(fill="x",padx=8,pady=(0,8))
        ctk.CTkCheckBox(row,text="Track visible weather",variable=self.weather_enabled_var).pack(side="left",padx=4)
        ctk.CTkCheckBox(row,text="Detect lightning + save 5-second clips",variable=self.lightning_enabled_var).pack(side="left",padx=14)
        ctk.CTkLabel(
            skysettings,
            text=("Strike clips are saved at the full resolution of the active camera feed. "
                  "Maximum Accuracy mode requests 1920×1080 when the camera supports it."),
            text_color="#9aa7b4",wraplength=930,justify="left"
        ).pack(anchor="w",padx=12,pady=(0,12))

        zones=ctk.CTkFrame(frame,corner_radius=12)
        zones.pack(fill="x",padx=16,pady=6)
        ctk.CTkLabel(zones,text="Zones",font=ctk.CTkFont(size=16,weight="bold")).pack(anchor="w",padx=12,pady=(12,4))
        ctk.CTkLabel(
            zones,text="Choose a zone, then drag a rectangle over the live camera on the Monitor page.",
            text_color="#9aa7b4"
        ).pack(anchor="w",padx=12,pady=(0,8))
        buttons=ctk.CTkFrame(zones,fg_color="transparent")
        buttons.pack(fill="x",padx=8,pady=(0,12))
        for name,title in [("road","Road"),("driveway","Driveway"),("sidewalk","Sidewalk"),("ignore","Ignore")]:
            ctk.CTkButton(buttons,text=f"Draw {title}",width=105,command=lambda n=name:self.begin_zone(n)).pack(side="left",padx=4)
            ctk.CTkButton(buttons,text="Clear",width=58,fg_color="#374151",command=lambda n=name:self.clear_zone(n)).pack(side="left",padx=(0,8))

        learning=ctk.CTkFrame(frame,corner_radius=12)
        learning.pack(fill="x",padx=16,pady=6)
        ctk.CTkLabel(learning,text="Adaptive tuning",font=ctk.CTkFont(size=16,weight="bold")).pack(anchor="w",padx=12,pady=(12,4))
        ctk.CTkLabel(
            learning,text="Use these after a real mistake. Titus gently adjusts thresholds for this fixed camera.",
            text_color="#9aa7b4"
        ).pack(anchor="w",padx=12,pady=(0,8))
        row=ctk.CTkFrame(learning,fg_color="transparent")
        row.pack(fill="x",padx=8,pady=(0,12))
        ctk.CTkButton(row,text="That was a false alarm",command=self.learn_false_alarm).pack(side="left",padx=4)
        ctk.CTkButton(row,text="You missed an event",command=self.learn_missed).pack(side="left",padx=4)

        data=ctk.CTkFrame(frame,corner_radius=12)
        data.pack(fill="x",padx=16,pady=6)
        ctk.CTkLabel(data,text="Data",font=ctk.CTkFont(size=16,weight="bold")).pack(anchor="w",padx=12,pady=(12,4))
        row=ctk.CTkFrame(data,fg_color="transparent")
        row.pack(fill="x",padx=8,pady=(4,12))
        ctk.CTkButton(row,text="Backup Titus data",command=self.backup_data).pack(side="left",padx=4)
        ctk.CTkButton(row,text="Open data folder",command=lambda:os.startfile(str(self.app_dir/"data"))).pack(side="left",padx=4)
        ctk.CTkButton(row,text="Export CSV",command=self.export_csv).pack(side="left",padx=4)

        ctk.CTkButton(frame,text="Save settings",height=42,fg_color="#1d4ed8",command=self.save_settings).pack(anchor="w",padx=16,pady=(12,24))

    # ------------------------------------------------------------------
    # Camera / zone actions
    # ------------------------------------------------------------------
    def find_cameras(self):
        if self.engine.running:
            messagebox.showinfo("Titus","Stop monitoring before scanning cameras.")
            return
        self.status_label.configure(text="Finding cameras...")
        self.engine.scan_cameras_async()

    def start_monitoring(self):
        source=self.camera_var.get().strip()
        self.save_settings(silent=True)
        self.settings.data["camera_source"]=source.replace("Camera ","")
        self.settings.save()
        self.status_label.configure(text="Opening camera...")
        self.engine.start(source)

    def stop_monitoring(self):
        self.status_label.configure(text="Stopping...")
        self.engine.stop()

    def manual_snapshot(self):
        if self.latest_frame is None:
            return
        folder=self.app_dir/"data"/"snapshots"
        folder.mkdir(parents=True,exist_ok=True)
        path=folder/f"manual_{datetime.now():%Y%m%d_%H%M%S}.jpg"
        cv2.imwrite(str(path),self.latest_frame)
        self._flash_alert("Snapshot saved",level="notice")

    def begin_zone(self,name):
        self.zone_draw_mode=name
        self._show_view("monitor")
        self._flash_alert(f"Draw {name.upper()} zone: drag a rectangle on the camera",level="notice")

    def clear_zone(self,name):
        self.engine.zones.clear_zone(name)
        self._flash_alert(f"{name.title()} zone cleared",level="notice")

    def _zone_mouse_down(self,event):
        if self.zone_draw_mode:
            self.zone_drag_start=(event.x,event.y)

    def _zone_mouse_up(self,event):
        if not self.zone_draw_mode or self.zone_drag_start is None or self.display_geometry is None:
            return
        iw,ih,ox,oy=self.display_geometry
        def conv(px,py):
            return (
                max(0,min(iw,px-ox))/max(iw,1),
                max(0,min(ih,py-oy))/max(ih,1),
            )
        x1,y1=conv(*self.zone_drag_start)
        x2,y2=conv(event.x,event.y)
        name=self.zone_draw_mode
        self.engine.zones.set_zone(name,(x1,y1,x2,y2))
        self.zone_draw_mode=None
        self.zone_drag_start=None
        self._flash_alert(f"{name.title()} zone saved",level="notice")

    # ------------------------------------------------------------------
    # Event actions
    # ------------------------------------------------------------------
    def open_selected_photo(self):
        if self.selected_event_snapshot and Path(self.selected_event_snapshot).exists():
            os.startfile(self.selected_event_snapshot)

    def bookmark_selected(self):
        if not self.selected_event_code:
            return
        value=self.db.toggle_bookmark(self.selected_event_code)
        if value is not None:
            self._flash_alert("Bookmarked" if value else "Bookmark removed",level="notice")
            self._refresh_events()

    def note_selected(self):
        if not self.selected_event_code:
            return
        current=self.db.get_event(self.selected_event_code)
        note=simpledialog.askstring("Titus","Note for this event:",initialvalue=current["note"] if current else "")
        if note is not None:
            self.db.set_note(self.selected_event_code,note)
            self._refresh_events()

    def name_selected(self):
        if not self.selected_event_code:
            return
        row=self.db.get_event(self.selected_event_code)
        if not row:
            return
        current=row["display_name"] or ""
        prompt="Name this recurring vehicle/animal:" if row["persistent_id"] else "Label this recorded event:"
        name=simpledialog.askstring("Titus",prompt,initialvalue=current)
        if name is None:
            return
        if row["persistent_id"]:
            self.db.name_identity(row["persistent_id"],name)
        self.db.set_display_name(self.selected_event_code,name)
        self._flash_alert(f"Saved label: {name}",level="notice")
        self._refresh_events()
        refreshed=self.db.get_event(self.selected_event_code)
        if refreshed:
            self.select_event(dict(refreshed))

    def mark_selected_reviewed(self):
        if not self.selected_event_code:
            return
        self.db.mark_reviewed(self.selected_event_code,True)
        self._flash_alert("Event marked reviewed",level="notice")
        self._refresh_events()
        self._refresh_monitor_cards()

    # ------------------------------------------------------------------
    # Settings / learning
    # ------------------------------------------------------------------
    def save_settings(self,silent=False):
        s=self.settings.data
        s["confidence"]=float(self.conf_var.get())
        s["motion_sensitivity"]=float(self.motion_var.get())
        s["night_assist"]=bool(self.night_var.get())
        s["headlight_assist"]=bool(self.headlight_var.get())
        s["monitor_vehicles"]=bool(self.vehicle_var.get())
        s["monitor_people"]=bool(self.people_var.get())
        s["monitor_animals"]=bool(self.animal_var.get())
        s["voice_alerts"]=bool(self.voice_var.get())
        s["sound_alerts"]=bool(self.sound_var.get())
        s["tripwire_orientation"]=self.orientation_var.get()
        s["tripwire_position"]=float(self.tripwire_var.get())
        s["speed_mode"]=self.speed_mode_var.get()
        s["speed_gate_a"]=float(self.speed_a_var.get())
        s["speed_gate_b"]=float(self.speed_b_var.get())
        try:
            s["speed_distance_ft"]=max(1.0,float(self.speed_distance_var.get()))
        except Exception:
            s["speed_distance_ft"]=30.0
        s["night_threshold"]=float(self.night_threshold_var.get())
        s["performance_mode"]=self.performance_var.get()
        s["auto_start_monitoring"]=bool(self.auto_start_var.get())
        s["weather_enabled"]=bool(self.weather_enabled_var.get())
        s["lightning_enabled"]=bool(self.lightning_enabled_var.get())
        # Titus intentionally keeps lightning clips at five seconds for a
        # predictable pre/post-roll review experience.
        s["lightning_clip_seconds"]=5.0
        self.settings.save()
        if not silent:
            self._flash_alert("Settings saved",level="notice")

    def learn_false_alarm(self):
        self.settings.learn_false_alarm()
        self.conf_var.set(float(self.settings.data["confidence"]))
        self.motion_var.set(float(self.settings.data["motion_sensitivity"]))
        self.db.add_feedback("false_alarm",self.selected_event_code)
        self._flash_alert("Learned: Titus will be slightly stricter",level="notice")

    def learn_missed(self):
        self.settings.learn_missed()
        self.conf_var.set(float(self.settings.data["confidence"]))
        self.motion_var.set(float(self.settings.data["motion_sensitivity"]))
        self.db.add_feedback("missed_event",self.selected_event_code)
        self._flash_alert("Learned: Titus will be slightly more sensitive",level="notice")

    # ------------------------------------------------------------------
    # Files / backup
    # ------------------------------------------------------------------
    def export_csv(self):
        path=filedialog.asksaveasfilename(
            title="Export Titus events",defaultextension=".csv",
            filetypes=[("CSV","*.csv")],
            initialfile=f"Titus-events-{datetime.now():%Y-%m-%d}.csv"
        )
        if path:
            self.db.export_csv(path)
            self._flash_alert("CSV exported",level="notice")

    def backup_data(self):
        dest=filedialog.asksaveasfilename(
            title="Backup Titus data",defaultextension=".zip",
            filetypes=[("ZIP","*.zip")],
            initialfile=f"Titus-backup-{datetime.now():%Y%m%d-%H%M}.zip"
        )
        if not dest:
            return
        data_dir=self.app_dir/"data"
        with zipfile.ZipFile(dest,"w",zipfile.ZIP_DEFLATED) as z:
            for p in data_dir.rglob("*"):
                if p.is_file():
                    z.write(p,p.relative_to(self.app_dir))
        self._flash_alert("Backup created",level="notice")

    # ------------------------------------------------------------------
    # Fullscreen
    # ------------------------------------------------------------------
    def toggle_fullscreen(self):
        if self.fullscreen_window is not None:
            self.exit_fullscreen()
            return
        win=ctk.CTkToplevel(self.root)
        win.title("Titus — Fullscreen Camera")
        win.attributes("-fullscreen",True)
        win.bind("<Escape>",lambda _e:self.exit_fullscreen())
        win.bind("<F11>",lambda _e:self.exit_fullscreen())
        label=ctk.CTkLabel(win,text="Waiting for camera...",fg_color="#000000")
        label.pack(fill="both",expand=True)
        self.fullscreen_window=win
        self.fullscreen_label=label

    def exit_fullscreen(self):
        if self.fullscreen_window is not None:
            try:self.fullscreen_window.destroy()
            except Exception:pass
        self.fullscreen_window=None
        self.fullscreen_label=None
        self.fullscreen_photo=None

    # ------------------------------------------------------------------
    # Polling / live display
    # ------------------------------------------------------------------
    def _poll(self):
        try:
            frame=self.frame_queue.get_nowait()
            self.latest_frame=frame.copy()
            self._show_frame(frame)
        except queue.Empty:
            pass

        try:
            while True:
                kind,payload=self.event_queue.get_nowait()
                if kind=="status":
                    self.status_label.configure(text=str(payload))
                    self.live_status.configure(text=str(payload))
                elif kind=="error":
                    self.status_label.configure(text="Error")
                    messagebox.showerror("Titus",str(payload))
                elif kind=="camera_scan":
                    cams=[f"Camera {i}" for i in payload]
                    if cams:
                        self.camera_menu.configure(values=cams)
                        if self.camera_var.get() not in cams:
                            self.camera_var.set(cams[0])
                        self._flash_alert(f"Found {len(cams)} camera{'s' if len(cams)!=1 else ''}",level="notice")
                    else:
                        self._flash_alert("No cameras answered the scan",level="warning")
                elif kind=="stats":
                    self._handle_stats(payload)
                elif kind=="event":
                    self._handle_event(payload)
                elif kind=="speed_update":
                    self._refresh_monitor_cards()
                    if self.current_view=="events":
                        self._refresh_events()
                    if self.current_view=="insights":
                        self._refresh_insights()
                elif kind=="weather":
                    self._handle_weather(payload)
                elif kind=="lightning":
                    self._handle_lightning(payload)
                elif kind=="lightning_clip_ready":
                    if self.current_view=="weather":
                        self._refresh_weather_view()
                    self._refresh_monitor_cards()
                elif kind=="alert":
                    self._handle_alert(payload)
        except queue.Empty:
            pass

        self.root.after(40,self._poll)

    def _show_frame(self,frame):
        rgb=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)
        pil=Image.fromarray(rgb)
        self.root.update_idletasks()
        w=max(self.video_label.winfo_width(),640)
        h=max(self.video_label.winfo_height(),360)
        scale=min(w/pil.width,h/pil.height)
        nw,nh=max(1,int(pil.width*scale)),max(1,int(pil.height*scale))
        resized=pil.resize((nw,nh),Image.Resampling.LANCZOS)
        img=ctk.CTkImage(light_image=resized,dark_image=resized,size=(nw,nh))
        self.camera_photo=img
        self.video_label.configure(image=img,text="")
        self.display_geometry=(nw,nh,(w-nw)//2,(h-nh)//2)

        if self.fullscreen_label is not None and self.fullscreen_window is not None:
            sw=max(self.fullscreen_window.winfo_width(),800)
            sh=max(self.fullscreen_window.winfo_height(),600)
            scale2=min(sw/pil.width,sh/pil.height)
            fw,fh=int(pil.width*scale2),int(pil.height*scale2)
            fimg=pil.resize((fw,fh),Image.Resampling.LANCZOS)
            fp=ctk.CTkImage(light_image=fimg,dark_image=fimg,size=(fw,fh))
            self.fullscreen_photo=fp
            self.fullscreen_label.configure(image=fp,text="")

    def _handle_stats(self,p):
        self.live_objects_label.configure(
            text=f"{p['vehicles']} moving vehicles • {p['people']} people • {p['animals']} animals"
        )
        self.ai_perf_label.configure(text=f"AI {p['infer_ms']:.0f} ms • {p['fps']:.1f} FPS")
        night=" • Night Assist" if p["night_active"] else ""
        self.quality_label.configure(text=f"Camera {p['quality']['label']}{night}")

    def _handle_event(self,row):
        self._refresh_monitor_cards()
        if self.current_view=="events":
            self._refresh_events()
        if self.current_view=="insights":
            self._refresh_insights()
        text=f"{row['happened_at'][11:19]}  {row['category'].title()}  {row['object_type']}"
        if row.get("color"):
            text += f"  {row['color']}"
        if row.get("zone"):
            text += f"  [{row['zone']}]"
        self.recent_activity.configure(state="normal")
        self.recent_activity.insert("1.0",text+"\n")
        content=self.recent_activity.get("1.0","end").splitlines()[:12]
        self.recent_activity.delete("1.0","end")
        self.recent_activity.insert("1.0","\n".join(content))
        self.recent_activity.configure(state="disabled")

    def _handle_weather(self,p):
        self.current_weather=dict(p)
        if hasattr(self,"today_cards"):
            self.today_cards["weather"].configure(text=str(p.get("condition","Unknown")))
        if self.current_view=="weather":
            self._refresh_weather_view()

    def _handle_lightning(self,p):
        self._refresh_monitor_cards()
        if self.current_view=="weather":
            self._refresh_weather_view()
        self._flash_alert(
            f"⚡ Lightning detected • {p.get('strike_code','strike')} • 5-second clip recording",
            level="warning"
        )

    def _handle_alert(self,p):
        self._flash_alert(p.get("text","Activity detected"),p.get("level","notice"))
        if self.settings.data.get("sound_alerts",True) and winsound is not None:
            try:winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:pass
        if self.settings.data.get("voice_alerts",True):
            self.speech.say(p.get("speech",""))

    def _flash_alert(self,text,level="notice"):
        colors={
            "vehicle":"#1d4ed8","person":"#7c3aed","animal":"#15803d",
            "warning":"#b45309","notice":"#334155"
        }
        color=colors.get(level,"#334155")
        self.alert_token += 1
        token=self.alert_token
        self.alert_dot.configure(text_color=color)
        self.alert_label.configure(text=text)
        def reset():
            if token==self.alert_token:
                self.alert_dot.configure(text_color="#6d7a8a")
                self.alert_label.configure(text="Titus monitoring" if self.engine.running else "Titus ready")
        self.root.after(5000,reset)

    def _refresh_monitor_cards(self):
        if not hasattr(self,"today_cards"):
            return
        s=self.db.stats_for_day()
        vals={
            "vehicles":str(s["vehicles"]),"people":str(s["people"]),"animals":str(s["animals"]),
            "driveway":str(s["driveway"]),
            "max_speed":f"{s['max_speed']:.0f} mph" if s["max_speed"] else "—",
            "weather":str(self.current_weather.get("condition","Unknown")),
            "lightning":str(self.db.lightning_stats_today()["count"]),
            "unreviewed":str(s["unreviewed"]),
        }
        for k,v in vals.items():
            self.today_cards[k].configure(text=v)

    def _close(self):
        try:self.engine.stop()
        except Exception:pass
        try:self.speech.stop()
        except Exception:pass
        try:self.db.close()
        except Exception:pass
        self.root.destroy()
