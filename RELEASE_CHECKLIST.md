# Mecatech Pointage v2.2.3 — Production Release Checklist

## Engineering gates
- [ ] `python -m compileall -q .` succeeds.
- [ ] `python -m unittest discover -s tests -p "test_*.py" -v` succeeds on Windows with project dependencies installed.
- [ ] Frontend templates render and embedded JavaScript syntax checks pass.
- [ ] ESP contract test passes with the expected SHA-256.
- [ ] No production `attendance.db` or backup files are tracked.

## Functional acceptance
- [ ] Login works and the administrator changes the default password.
- [ ] Dashboard, Workers, Leave and Settings navigation works.
- [ ] Settings save persists app name/theme/language/color/schedule values.
- [ ] Auto Check-out can be enabled and closes overdue open IN records.
- [ ] Worker add/edit/delete works.
- [ ] RFID enrollment still works with the existing ESP32.
- [ ] Attendance report shows calendar and full log.
- [ ] Attendance edit supports date/time and IN/OUT changes; invalid sequences are rejected.
- [ ] Attendance delete works and is audited.
- [ ] PDF preview opens with Back, Print and Download.
- [ ] Leave add/delete works and overlapping leave is rejected.
- [ ] Backup creates a valid SQLite copy.
- [ ] Restore validates the DB before replacement.

## Windows release
- [ ] GitHub Actions is green.
- [ ] `MecatechPointage-Setup-2.2.3.exe` installs successfully on a clean Windows PC.
- [ ] Existing real data is backed up before upgrade.
- [ ] Real ESP32 scans and heartbeat behavior are unchanged after upgrade.
