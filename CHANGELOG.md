# Changelog

## Titus 1.1 — Sky & Storm
- Added dedicated Sky & Storm dashboard.
- Added camera-based Sunny / Cloudy / Rainy / Night / Thunderstorm estimates with confidence.
- Added visual rain signal and cloudiness scoring.
- Added scene-wide lightning flash detection designed to reject localized headlights.
- Added daily lightning strike counter and lightning history.
- Added full-resolution lightning still photos.
- Added automatic 5-second lightning clips with pre-roll and post-roll.
- Added saved-clip status and one-click playback.
- Added weather history samples to the local SQLite database.
- Added weather and lightning information to the daily summary and Monitor cards.
- Added 1080p camera request when Maximum Accuracy mode is selected.
- Kept weather/lightning monitoring active even while the object-detection AI is still loading.

## Titus 1.0 — Daily Monitor
- Created separate Titus application and repository.
- Added modern dark dashboard with Monitor, Event Inbox, Insights, and Settings.
- Added camera picker and multi-backend Windows camera startup.
- Added camera-first startup while AI loads.
- Added local YOLO tracking.
- Added parked-vehicle suppression based on sustained motion.
- Added people and animal events.
- Added road / driveway / sidewalk / ignore zones.
- Added low-light enhancement and headlight assist.
- Added best-frame snapshots.
- Added likely-repeat vehicle/animal IDs.
- Added estimated vehicle speed with confidence.
- Added searchable event inbox, bookmarks, notes, and reviewed state.
- Added daily statistic cards, hourly activity visualization, and daily brief.
- Added CSV export, local ZIP backup, full-screen camera, camera diagnostics, and adaptive tuning.
