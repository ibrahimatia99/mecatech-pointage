"""Create deterministic demo attendance data for testing.

Usage:
  python seed_demo_data.py
  python seed_demo_data.py --reset

The script uses the app's configured database directory by default.
It creates four workers, realistic historical attendance, and two special
open-IN records for testing automatic check-out recovery.
"""

import argparse
import os
import random
import sqlite3
from datetime import datetime, timedelta

from db import get_db, init_db


SAMPLE_WORKERS = [
    {"worker_id": "W1001", "name": "Sami Ben Ali", "cin": "08123456", "phone": "21620111222", "card_uid": "A1B2C3D4"},
    {"worker_id": "W1002", "name": "Mohamed Trabelsi", "cin": "09456789", "phone": "21620333444", "card_uid": "E5F6G7H8"},
    {"worker_id": "W1003", "name": "Youssef Gharbi", "cin": "07890123", "phone": "21620555666", "card_uid": "I9J0K1L2"},
    {"worker_id": "W1004", "name": "Amine Mansour", "cin": "05123987", "phone": "21620777888", "card_uid": "M3N4O5P6"},
]


def seed_demo_data(reset=True):
    init_db()
    conn = get_db()
    try:
        c = conn.cursor()
        if reset:
            c.execute("DELETE FROM logs")
            c.execute("DELETE FROM leaves")
            c.execute("DELETE FROM audit_log")
            c.execute("DELETE FROM joker_assignments")
            c.execute("DELETE FROM joker_cards")
            c.execute("DELETE FROM workers")
            c.execute("DELETE FROM sqlite_sequence WHERE name IN ('logs', 'workers', 'joker_cards', 'joker_assignments', 'audit_log', 'leaves')")

        # Insert workers if they do not already exist.
        for w in SAMPLE_WORKERS:
            c.execute(
                "INSERT OR IGNORE INTO workers (worker_id, name, cin, phone, card_uid) VALUES (?, ?, ?, ?, ?)",
                (w["worker_id"], w["name"], w["cin"], w["phone"], w["card_uid"]),
            )

        rng = random.Random(20261004)
        today = datetime.now().replace(second=0, microsecond=0)
        start_date = today - timedelta(days=40)
        entries = []

        for day_offset in range(41):
            current_day = start_date + timedelta(days=day_offset)
            if current_day.weekday() in (5, 6):
                continue
            for w in SAMPLE_WORKERS:
                if rng.random() < 0.08:
                    continue
                mi = rng.randint(-6, 10)
                lo = rng.randint(-3, 6)
                ai = rng.randint(-3, 6)
                eo = rng.randint(-6, 12)
                morning_in = current_day.replace(hour=8, minute=0) + timedelta(minutes=mi)
                lunch_out = current_day.replace(hour=12, minute=0) + timedelta(minutes=lo)
                lunch_in = current_day.replace(hour=13, minute=0) + timedelta(minutes=ai)
                evening_out = current_day.replace(hour=17, minute=0) + timedelta(minutes=eo)
                entries.extend([
                    (w["worker_id"], w["card_uid"], "IN", morning_in.strftime("%Y-%m-%d %H:%M:%S")),
                    (w["worker_id"], w["card_uid"], "OUT", lunch_out.strftime("%Y-%m-%d %H:%M:%S")),
                    (w["worker_id"], w["card_uid"], "IN", lunch_in.strftime("%Y-%m-%d %H:%M:%S")),
                    (w["worker_id"], w["card_uid"], "OUT", evening_out.strftime("%Y-%m-%d %H:%M:%S")),
                ])

        # Two deliberately open IN records. Use yesterday so they are always
        # overdue under normal 18:00 check-out settings and exercise recovery
        # after app restart as well.
        yesterday = (today - timedelta(days=1)).replace(hour=8, minute=7)
        for worker_id, card_uid in (("W1001", "A1B2C3D4"), ("W1002", "E5F6G7H8")):
            entries.append((worker_id, card_uid, "IN", yesterday.strftime("%Y-%m-%d %H:%M:%S")))

        entries.sort(key=lambda item: item[3])
        c.executemany(
            "INSERT INTO logs (worker_id, card_uid, action, timestamp) VALUES (?, ?, ?, ?)",
            entries,
        )
        conn.commit()
        return len(entries)
    finally:
        conn.close()


def create_standalone_demo_db(output_path):
    output_path = os.path.abspath(os.path.expanduser(output_path))
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    if os.path.exists(output_path):
        os.remove(output_path)
    # The application's schema is deliberately duplicated here so the file is
    # portable and does not depend on the user's live application DB.
    conn = sqlite3.connect(output_path)
    conn.row_factory = sqlite3.Row
    try:
        c = conn.cursor()
        c.executescript("""
        CREATE TABLE workers (id INTEGER PRIMARY KEY AUTOINCREMENT, worker_id TEXT UNIQUE, name TEXT NOT NULL, cin TEXT, phone TEXT, card_uid TEXT UNIQUE);
        CREATE TABLE logs (id INTEGER PRIMARY KEY AUTOINCREMENT, worker_id TEXT NOT NULL, card_uid TEXT, action TEXT NOT NULL, timestamp DATETIME NOT NULL);
        CREATE TABLE joker_cards (id INTEGER PRIMARY KEY AUTOINCREMENT, card_uid TEXT UNIQUE, label TEXT NOT NULL);
        CREATE TABLE joker_assignments (id INTEGER PRIMARY KEY AUTOINCREMENT, joker_uid TEXT NOT NULL, worker_id TEXT NOT NULL, assigned_date TEXT NOT NULL);
        CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            actor TEXT NOT NULL DEFAULT 'admin',
            action TEXT NOT NULL,
            entity_type TEXT,
            entity_id TEXT,
            details TEXT
        );
        CREATE TABLE leaves (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worker_id TEXT NOT NULL,
            leave_type TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            note TEXT,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX idx_logs_worker_timestamp ON logs(worker_id, timestamp DESC, id DESC);
        CREATE INDEX idx_logs_timestamp ON logs(timestamp);
        CREATE INDEX idx_logs_action_timestamp ON logs(action, timestamp);
        CREATE INDEX idx_joker_assignments_uid_date ON joker_assignments(joker_uid, assigned_date);
        CREATE INDEX idx_joker_assignments_worker_date ON joker_assignments(worker_id, assigned_date);
        CREATE INDEX idx_audit_timestamp ON audit_log(timestamp DESC, id DESC);
        CREATE INDEX idx_leaves_worker_dates ON leaves(worker_id, start_date, end_date);
        INSERT INTO schema_meta(key,value) VALUES('schema_version','4');
        """)
        rng = random.Random(20261004)
        today = datetime.now().replace(second=0, microsecond=0)
        start_date = today - timedelta(days=20)
        for w in SAMPLE_WORKERS:
            c.execute("INSERT INTO workers(worker_id,name,cin,phone,card_uid) VALUES(?,?,?,?,?)", tuple(w.values()))
            for d in range(21):
                day = start_date + timedelta(days=d)
                if day.weekday() in (5, 6):
                    continue
                a = day.replace(hour=8, minute=rng.randint(0, 12))
                b = day.replace(hour=12, minute=rng.randint(0, 8))
                ci = day.replace(hour=13, minute=rng.randint(0, 8))
                e = day.replace(hour=17, minute=rng.randint(0, 15))
                for action, stamp in (("IN",a),("OUT",b),("IN",ci),("OUT",e)):
                    c.execute("INSERT INTO logs(worker_id,card_uid,action,timestamp) VALUES(?,?,?,?)", (w["worker_id"],w["card_uid"],action,stamp.strftime("%Y-%m-%d %H:%M:%S")))
        yesterday = (today - timedelta(days=1)).replace(hour=8, minute=7)
        for worker_id, card_uid in (("W1001", "A1B2C3D4"),("W1002", "E5F6G7H8")):
            c.execute("INSERT INTO logs(worker_id,card_uid,action,timestamp) VALUES(?,?,?,?)", (worker_id,card_uid,"IN",yesterday.strftime("%Y-%m-%d %H:%M:%S")))

        # Leave examples for calendar/report testing.
        monday = today + timedelta(days=(7 - today.weekday()) % 7)
        for worker_id, leave_type in (("W1003", "Vacation"),("W1004", "Authorized absence")):
            c.execute("INSERT INTO leaves(worker_id,leave_type,start_date,end_date,note) VALUES(?,?,?,?,?)", (worker_id, leave_type, monday.date().isoformat(), (monday + timedelta(days=1)).date().isoformat(), "Demo record"))

        c.execute("INSERT INTO audit_log(timestamp,actor,action,entity_type,entity_id,details) VALUES(?,?,?,?,?,?)", (today.strftime("%Y-%m-%d %H:%M:%S"), "demo", "demo_seeded", "database", None, "Deterministic production feature demo data"))
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create deterministic Mecatech Pointage demo data")
    parser.add_argument("--keep", action="store_true", help="Keep existing workers/logs instead of clearing them")
    parser.add_argument("--output", help="Also create a standalone SQLite demo database at this path")
    args = parser.parse_args()
    total = seed_demo_data(reset=not args.keep)
    print(f"Demo database populated successfully: {total} attendance records.")
    if args.output:
        create_standalone_demo_db(args.output)
        print(f"Standalone demo database created: {os.path.abspath(args.output)}")
