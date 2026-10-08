# Titus — Local Vision Monitor

**Titus** is a Windows-first, local-AI monitoring dashboard for a fixed camera watching a street, driveway, sidewalk, or front of a home.

Titus was designed from the lessons learned while building StreetWatch, but it is a separate application with a cleaner daily workflow and a stronger focus on monitoring, review, and statistics.

## What makes Titus different

- **Fast camera-first startup** — the live camera opens before the AI finishes warming up.
- **Camera picker** — scan local cameras and choose the one you actually want.
- **Parked-object suppression** — vehicles must show sustained motion before they create traffic events.
- **Day / night pipeline** — automatic low-light enhancement and moving-headlight assist.
- **Local AI** — normal camera processing, event history, snapshots, and statistics stay on the PC.
- **Event Inbox** — review vehicles, people, and animals in one searchable timeline.
- **Daily dashboard** — today’s totals, estimated speeds, busiest hour, driveway activity, repeat IDs, system health, current visual weather, and lightning count.
- **Persistent vehicle / animal IDs** — likely-repeat matching for vehicles and animals, with confidence rather than false certainty.
- **Person visit events** — people get event IDs and snapshots; Titus does not automatically identify people by face.
- **Zones** — ROAD, DRIVEWAY, SIDEWALK, and IGNORE areas.
- **Estimated speed** — automatic monocular estimate shown with a confidence level; optional calibrated gates can improve accuracy.
- **Best-frame snapshots** — Titus keeps the clearest crop it sees during the track.
- **Adaptive tuning** — “false alarm” and “missed event” feedback gently tunes detection parameters for that fixed camera.
- **Camera health** — live FPS, inference time, brightness, blur/quality, reconnect state.
- **Sky & Storm** — camera-based Sunny / Cloudy / Rainy / Night / Thunderstorm estimates with confidence.
- **Lightning counter** — detects likely scene-wide lightning flashes and counts them by day.
- **5-second lightning clips** — saves a high-quality still plus a 5-second pre/post-roll clip at the full resolution of the active camera feed.
- **Lightning history** — dedicated page with strike IDs, time, weather estimate, confidence, photo, and playable clip.
- **One-click fullscreen** — turn the app into a clean live monitor.
- **CSV export + local backup** — your history remains portable.

## Daily-use design

The app is organized into four main views:

1. **Monitor** — big live camera, alert banner, camera controls, live objects, and today cards.
2. **Events** — searchable event inbox with photos, notes, bookmarks, and filters.
3. **Insights** — hourly activity, category totals, estimated-speed statistics, repeat activity, and a plain-English daily brief.
4. **Settings** — camera, detection, zones, night mode, data retention, and learning controls.

## Quick start on Windows

1. Download / clone this repo.
2. Double-click `INSTALL_AND_RUN.bat` once.
3. After installation, use `RUN_TITUS.bat`.
4. Click **Find Cameras**.
5. Pick the camera pointed at the street / driveway.
6. Click **Start Monitoring**.

The first setup downloads the small YOLO model once.

## Privacy

Titus is designed for local processing. Event data is stored under `data/`. The repo ignores model weights, databases, snapshots, virtual environments, and build output.

## Speed note

Uncalibrated speed is shown as an **estimate** with confidence. A single ordinary camera does not know real-world scale by itself. Titus can optionally use two calibrated gates with a known distance for a much stronger estimate.

## People

Titus can detect and log people, save a snapshot, and assign a visit/event ID. It intentionally does not perform automatic facial identification.

## Status

Current repo target: **Titus 1.1 — Sky & Storm**
