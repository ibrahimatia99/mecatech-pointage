# Mecatech Pointage v2.2.3 — Production Software Audit

## Release scope
This release is the result of a source-level software-engineering audit of the desktop attendance application. The ESP-facing communication boundary is explicitly frozen.

## Critical defects found and fixed

### Settings Save appearing to hang
The Settings page previously relied on the same multipart/native path used for file uploads. In a desktop WebView this could leave the UI waiting without a useful error. The release adds a dedicated `/api/settings/update-fast` endpoint that only validates and atomically writes `config.json`; it does not open SQLite or wait for audit/maintenance work. The browser now submits ordinary settings as URL-encoded data, has a 12-second timeout, shows explicit success/error state, and uses a separate asset upload endpoint when a logo/icon is selected. The original `/api/settings/update` remains as the no-JavaScript/native fallback.

### Global navigation failure
A translation entry contained an unescaped apostrophe (`Today's Attendance`) inside a single-quoted JavaScript string. That syntax error prevented the dashboard script from loading, making Workers, Leave, and Settings appear non-responsive. The string and frontend regression checks were corrected.

### WebView storage robustness
Theme/tab persistence could throw a storage `SecurityError` in restricted origins. Storage access is now wrapped in safe helpers so storage failure cannot break navigation or settings UI.

### Database/runtime reliability
Database autodiscovery is performed once per process; SQLite WAL setup is configured once per database path; maintenance operations are rate-limited so frequent ESP heartbeats cannot repeatedly scan/purge SQLite. Restore validation removes stale WAL/SHM sidecars.

### Attendance integrity
Manual log edits validate date/time/action and reject an edit that would create an invalid consecutive IN/IN or OUT/OUT sequence. Worker deletion removes associated attendance, leave, and Joker assignment records transactionally. Leave creation rejects overlapping ranges.

### Operational safeguards
The desktop application fails fast if its fixed local service port is already owned by another process, uses a rotating local log, validates backup integrity, and keeps automatic backups bounded.

## Requested product features included
- Worker status dashboard
- Daily attendance panel
- Late-arrival detection
- Worked-time calculation
- Audit trail
- Backup/restore
- PDF reporting
- Monthly employee reports
- Calendar attendance view
- Leave management
- Manual attendance correction and deletion
- Background automatic check-out
- English/French/Arabic interface

Excel/CSV report buttons are removed from the GUI as requested; the server export endpoints remain available for compatibility unless a future release deliberately removes them.

## ESP protection
The protected ESP-facing region in `routes/api.py` is checked by `tests/test_esp_contract.py`. Its SHA-256 is required to remain:

`6f43a814c7c2e4709cbb4628ec23db37beaee4069b698246fcd4e70a2802fa04`

No ESP firmware change is required for v2.2.3.

## Verification performed in this environment
- Python compilation for all project modules: PASS
- Jinja2 rendering for all HTML templates: PASS
- Node syntax validation for rendered JavaScript: PASS
- Navigation/frontend regression tests: PASS
- ESP communication contract test: PASS
- Isolated settings persistence test: PASS
- Auto-checkout idempotency test: PASS
- SQLite backup/restore integrity test: PASS

The environment does not contain the application's optional Flask/Waitress/pywebview/zeroconf runtime packages, so the full desktop process and Windows executable cannot be executed here. The GitHub Actions Windows workflow remains the authoritative CI/build environment for dependency installation, full tests, PyInstaller, and Inno Setup.
