# Auto check-out test

1. Start Mecatech Pointage.
2. Open **Settings → App Parameters**.
3. Enable **AUTO CHECK-OUT**.
4. Set a trigger time after the configured check-out time, for example Trigger `20:00` and Check-out `18:00`.
5. Use the bundled `demo_data/attendance_demo.db` (or generate it with `seed_demo_data.py`).
6. Restart the application or wait for its maintenance cycle.
7. Open a worker report and confirm that an open IN from a previous day received an OUT at the configured check-out time.

There is intentionally no manual Auto Check-out button in the production GUI.
