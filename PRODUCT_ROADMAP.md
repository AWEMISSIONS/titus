# Titus Product Roadmap

Titus is meant to be something a person can leave running every day and understand in seconds.

## Product principles

1. **Live view first.** The camera should appear quickly even if AI is still warming.
2. **Useful events, not noise.** Parked cars and static scenery should not flood the event list.
3. **One place to review the day.** A user should not need to inspect raw logs.
4. **Confidence over pretending.** Estimated speed and repeat-ID matches show confidence.
5. **Local by default.** Normal detection, photos, logs, and statistics stay on the computer.
6. **Recover automatically.** Camera disconnects and temporary failures should not require babysitting.
7. **Make corrections easy.** Feedback should tune the fixed-camera setup without exposing technical settings.

## Titus 1.0 — implemented foundation

- Camera picker and backend fallback
- Camera-first startup while AI warms
- YOLO local detection/tracking
- Moving-vehicle gating / parked vehicle suppression
- Person and animal events
- Local event database
- Best-frame event snapshots
- Road / driveway / sidewalk / ignore zones
- Automatic low-light enhancement
- Moving-headlight night assist
- Vehicle / animal likely-repeat IDs
- Estimated vehicle speed with confidence
- Searchable Event Inbox
- Bookmark, note, reviewed/unreviewed state
- Today statistics
- Hourly activity graph
- Daily plain-English summary
- CSV export and local ZIP backup
- Camera health metrics
- Fullscreen camera
- Adaptive false-alarm / missed-event tuning
- Camera diagnostics utility

## Next updates I would prioritize

### P1 — Daily reliability
- **Event clip buffer:** save a short clip around bookmarked or driveway events without recording 24/7.
- **Best-frame gallery:** keep 2–3 strongest frames when one photo is not enough.
- **Retention manager:** automatic deletion of ordinary old snapshots while preserving bookmarks.
- **Disk-space warning:** visible warning before the drive fills.
- **Crash/watchdog recovery:** automatically relaunch the vision worker if it stops.
- **Start with Windows:** optional checkbox in the app, not a separate script.
- **Last-known-good camera:** if a camera number changes after reboot, rescan and recover.
- **Camera alignment warning:** warn if the view has shifted substantially from the saved normal view.

### P1 — Better monitoring
- **Driveway enter / exit state:** distinguish entering, parked, and leaving.
- **Stopped-on-road event:** log a moving vehicle that becomes stationary in a road zone for a meaningful period.
- **Return-pass grouping:** group likely same-vehicle passes close together into one story.
- **Event confidence explanation:** show why Titus logged an event: motion confirmed, zone, AI confidence, track length.
- **Rain / glare robustness:** adapt motion and night thresholds when rain, snow, or glare causes noise.
- **Window reflection mask helper:** guide the user to mark persistent glass reflections.
- **Two-stage AI:** fast detector for every frame, stronger second pass only on interesting crops.

### P1 — Better statistics
- **7-day / 30-day trends**
- **Traffic by hour and weekday**
- **Driveway visits by day**
- **Estimated speed distribution**
- **Repeat vehicle frequency**
- **New-vs-repeat likely vehicle count**
- **Event heat map over the camera image**
- **Compare today vs recent average**, not just yesterday
- **Morning / afternoon / evening summaries**
- **Printable daily/weekly report**

### P2 — Better review experience
- **Thumbnail filmstrip** under the live camera
- **Keyboard shortcuts** for bookmark / reviewed / false alarm
- **Side-by-side repeat vehicle comparison**
- **Saved filters** such as “driveway only” or “vehicles over ~35 MPH”
- **Event groups** that collapse multiple detections from one short visit
- **One-click “wrong type / wrong color” correction**
- **Calendar view** for historical activity
- **Timeline scrubber** instead of only a list

### P2 — Stronger recognition
- **Dedicated vehicle body-style classifier** for sedan / SUV / pickup / van / box truck.
- **Dedicated make/model model** when a trustworthy local model is available.
- **Better vehicle color segmentation** to avoid pavement/windows/headlights.
- **Plate-area crop** for clearer event review.
- **Optional local OCR** for a plate the user is legally permitted to monitor.
- **Animal species expansion** with a model trained for common local wildlife.

### P2 — Multi-camera
- 2–4 camera dashboard
- per-camera zones and settings
- camera-specific statistics
- picture-in-picture
- event handoff across adjacent cameras

## Things Titus should not fake

- Exact radar-grade speed from an uncalibrated single camera
- Exact make/model/year when the classifier is uncertain
- Perfect repeat-vehicle identity when two vehicles look alike
- Automatic facial identity of people

The goal is a monitoring app users trust because it tells them both **what it thinks** and **how sure it is**.
