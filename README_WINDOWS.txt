MECA-TECH ATIA - Mecatech Pointage
Windows desktop build

1. Run MecatechPointage.exe.
2. The application opens in its own desktop window.
3. No web browser is required.
4. The GUI does not require Internet access.
5. Database/configuration data are stored in the current Windows user's Local AppData folder unless a different database directory is selected in Settings.
6. The ESP32 can reach the local Flask service through the LAN on TCP port 5001. mDNS advertises the _mecatech._tcp service when available.

Default password: admin
Change it immediately in Settings.

PRODUCTION WINDOWS NOTES
------------------------
- The application uses Waitress instead of Flask's development server.
- SQLite uses WAL mode, busy timeout, synchronous NORMAL, indexes, and schema versioning.
- Database backups are created automatically in <database folder>\backups and the newest 7 are retained.
- Logs are written to %LOCALAPPDATA%\MecatechPointage\logs\mecatech-pointage.log with rotation.
- The installer opens TCP 5001 and mDNS UDP 5353 only for Windows Domain/Private profiles so the ESP32 can discover and reach the application.
- Application data is outside Program Files, so upgrades/uninstalls do not erase attendance data.
- The first successful login migrates the legacy plaintext password; new password changes are stored as secure password hashes.
- Never place the attendance database inside Program Files or a synchronized folder unless you have a controlled backup strategy.
