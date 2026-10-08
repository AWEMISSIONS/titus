# Titus — Complete Feature List

## Live monitoring
- Windows-first local monitoring dashboard.
- Large live camera view.
- Find Cameras scanner.
- Select Camera 0, Camera 1, etc.
- Editable camera source for compatible stream addresses.
- DirectShow, Media Foundation, then default OpenCV camera fallback.
- Fast camera-first startup while the AI warms in the background.
- Automatic camera reconnect after interrupted frames.
- Fullscreen live camera (including F11 / Escape workflow).
- One-click manual snapshot.
- Live moving-vehicle / person / animal counts.
- Live AI inference time and approximate FPS.
- Camera quality indicator based on brightness and sharpness.
- Fast / Balanced / Maximum Accuracy performance modes.
- Maximum Accuracy requests 1920×1080 when the camera supports it.

## Vehicle monitoring
- Local YOLO detection for car, motorcycle, bus, and truck.
- ByteTrack multi-object tracking.
- Real-time bounding boxes.
- Real-time motion trails.
- Parked/stationary vehicle suppression.
- Sustained-motion confirmation before a vehicle is treated as traffic.
- Vehicle color estimation.
- Low-light color can fall back to Unknown rather than forcing a bad guess.
- Road-event line for normal passing traffic.
- Left/right or toward/away traffic orientation.
- Driveway-zone vehicle logging without requiring the road event line.
- Direction saved with the event.
- Best-frame vehicle snapshot.
- Persistent likely-repeat vehicle IDs (TV-xxxx).
- Repeat-ID match confidence.
- User-assigned recurring vehicle names/labels.
- Future likely matches can carry the saved vehicle name.
- Searchable history by ID, type, color, zone, name, direction, or note.

## Speed
- Automatic no-setup camera speed estimate.
- Speed confidence shown instead of pretending the estimate is exact.
- Optional calibrated Speed Gate A / Speed Gate B mode.
- User-entered real distance between calibrated gates.
- Calibrated MPH saved to the event.
- Strong calibrated measurements gently tune the automatic camera speed scale.
- Daily average estimated speed.
- Daily fastest estimated speed.
- Speed stored in CSV exports.

## People
- Local person detection.
- A person does not need to cross the vehicle road line to be recorded.
- Confirmed person-entry event.
- Person event ID (P-xxxxxx).
- Best available event snapshot.
- Manual person event label/name.
- Searchable person history.
- Titus does not automatically identify people by face.

## Animals
- Local detection for supported YOLO animal classes including bird, cat, dog, horse, sheep, cow, elephant, bear, zebra, and giraffe.
- Animal event on confirmed entry.
- Persistent likely-repeat animal IDs (TA-xxxx).
- Repeat-match confidence.
- User-assigned pet/animal names.
- Future likely matches can carry the saved animal name.
- Animal snapshots and searchable history.

## Zones
- ROAD zone.
- DRIVEWAY zone.
- SIDEWALK zone.
- IGNORE zone.
- Draw zones directly over the live camera.
- Zone labels saved with events.
- Ignore zones suppress detections in reflections or areas you do not want monitored.

## Night monitoring
- Automatic Night Assist.
- Automatic brightness measurement.
- Gamma shadow lift.
- Local-contrast enhancement (CLAHE).
- Day/night transition without requiring manual switching.
- Moving-headlight assist for very dark scenes.
- Paired-headlight detection designed to ignore stationary lights.
- Night vehicle hint when the body is too dark for normal YOLO detection.
- Camera-quality warning for dark, blurry, or overexposed conditions.

## Sky & Storm
- Dedicated Sky & Storm dashboard.
- Camera-based visible-weather tracking.
- Sunny estimate.
- Cloudy estimate.
- Rainy estimate.
- Night state.
- Thunderstorm state when visual storm/lightning evidence is present.
- Weather confidence.
- Cloudiness score.
- Visual rain signal/confidence.
- Local weather-history samples stored in SQLite.
- Current weather shown on the Monitor dashboard.
- Dominant visual weather included in the daily brief.

## Lightning
- Real-time visual lightning detection from the raw camera feed.
- Lightning runs even while the object-detection AI is still loading.
- Scene-wide illumination analysis to reduce confusion with local car headlights.
- Lightning strike IDs (L-xxxxx).
- Daily lightning strike count.
- Lightning confidence.
- Lightning condition stored with each strike.
- High-quality full-resolution strike still image.
- Automatic five-second strike video.
- Roughly half the clip is pre-roll and half is post-roll so the flash is not only caught after the fact.
- Clip uses the full resolution currently being delivered by the selected camera.
- Maximum Accuracy mode requests 1080p for higher-resolution strike clips when supported.
- Dedicated lightning history list.
- One-click strike photo opening.
- One-click playback of completed five-second clips.
- Saved-clip status.
- Local lightning storage under data/lightning/.

## Event Inbox
- Unified searchable event history.
- Filter All / Vehicles / People / Animals.
- Zone filter.
- Bookmarked-only filter.
- Search event ID.
- Search object type.
- Search vehicle color.
- Search direction.
- Search zone.
- Search persistent ID.
- Search user name/label.
- Search event notes.
- Event detail panel.
- Event photo preview.
- Open original snapshot.
- Add notes.
- Add a name/label.
- Bookmark important events.
- Mark events reviewed.
- Reviewed/unreviewed count.

## Statistics and Insights
- Today vehicle count.
- Today person count.
- Today animal count.
- Driveway event count.
- Average estimated vehicle speed.
- Fastest estimated vehicle speed.
- Number of likely unique vehicles.
- Repeat-vehicle count in the database layer.
- Busiest hour.
- 24-hour activity chart.
- Direction statistics stored by event.
- Most repeated likely vehicles.
- Today-vs-yesterday activity comparison.
- Lightning count.
- Completed lightning-clip count.
- Automatic plain-English daily brief.

## Alerts
- Visual top-bar alerts.
- Different alert categories for vehicle, person, animal, warning, and notice.
- Optional Windows alert sound.
- Optional offline spoken alerts.
- Vehicle passed alert.
- Driveway vehicle alert.
- Person detected alert.
- Animal detected alert.
- Possible night vehicle/headlight alert.
- Lightning detected alert.

## Adaptive tuning
- “That was a false alarm” feedback.
- “You missed an event” feedback.
- Titus gently changes motion sensitivity and AI confidence.
- Learned values persist locally.
- Calibrated speed can tune the automatic speed scale.
- Titus does not silently rewrite its own source code.

## Data and privacy
- Normal camera AI processing is local.
- SQLite event database.
- Local snapshots.
- Local identity reference images.
- Local lightning clips.
- Local settings.
- CSV event export.
- ZIP backup of Titus data.
- Open data folder button.
- No cloud video processing required.

## Reliability / maintenance
- Camera diagnostics utility.
- Tests camera indices against multiple Windows camera backends.
- Shows whether a camera actually returns a frame.
- Local source verification script.
- GitHub Actions syntax/core smoke verification.
- Windows EXE build script.
- GitHub Actions Windows artifact build workflow.
- Separate source repository: AWEMISSIONS/titus.

## Important accuracy labels
- Uncalibrated speed is an estimate, not certified radar.
- Visual weather is a camera estimate, not an official weather station report.
- Rain detection depends on camera angle, visibility, and image quality.
- Repeat vehicle/animal IDs are likely matches, not guaranteed identity.
- Titus does not automatically identify people by face.
