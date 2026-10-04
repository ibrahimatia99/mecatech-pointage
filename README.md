# Mecatech Pointage

Mecatech Pointage is an offline-first Windows attendance application for the existing ESP32 RFID terminal. The PC application owns reporting, worker management, settings, backups, audit history and automatic check-out; the existing ESP32 communication contract remains unchanged.

## v2.2.3 — Production audit release

- Reliable native Settings save with server-side validation and explicit success feedback.
- Dashboard worker status cards and daily attendance metrics.
- Late-arrival and worked-hours calculations.
- Manual attendance correction (IN/OUT/date/time) with deletion and audit history.
- Monthly worker calendar and attendance log.
- PDF report preview with Back, Print and Download controls.
- Leave management with overlap validation.
- SQLite backup/restore with rotating backups.
- Offline multilingual GUI: English, French and Arabic.
- Database integrity protections and one-time demo database discovery for development/test use.
- Maintenance throttling so frequent ESP32 heartbeats do not repeatedly hammer SQLite.
- Production Windows build through GitHub Actions + PyInstaller + Inno Setup.

## Important

The application does not include a production attendance database. Runtime data is stored under the Windows user's LocalAppData directory by default. Keep `attendance.db`, backups, uploads and logs out of Git.

## Test data

Use `seed_demo_data.py` to create a local demonstration database. Demo `.db` files are ignored by Git and are not included in the Windows executable build.

## ESP32 compatibility

No ESP32 firmware update is required for v2.2.3. The ESP-facing section of `routes/api.py` is regression-tested with a fixed SHA-256 contract before a release is built.


## v2.2.3
- Removed dark mode; the application is light-theme only.
- Attendance log corrections allow date/time changes unless the edit introduces a new invalid adjacent action pair.
