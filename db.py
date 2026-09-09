import os
import json
import sqlite3
import platform
from datetime import datetime, timedelta

CONFIG_FILE = "config.json"

def get_default_db_dir():
    if platform.system() == "Windows":
        return "C:\\MecaTech_Data\\"
    return os.path.expanduser("~/MecaTech_Data/")

def load_config():
    default_config = {
        "db_path": get_default_db_dir(),
        "app_name": "Mecatech Pointage",
        "app_logo": "",
        "app_icon": "",
        "app_password": "admin",
        "theme": "light",
        "primary_color": "#7000ff",
        "purge_days": 30
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                cfg = json.load(f)
                if not cfg.get("db_path"):
                    cfg["db_path"] = get_default_db_dir()
                default_config.update(cfg)
        except Exception:
            pass
    return default_config

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=4)

def get_db():
    cfg = load_config()
    db_dir = cfg.get("db_path", get_default_db_dir())
    if not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
    db_file = os.path.join(db_dir, "attendance.db")
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    return conn

def purge_old_logs():
    """Deletes logs older than the purge_days setting."""
    cfg = load_config()
    purge_days = cfg.get("purge_days", 0)
    if purge_days and int(purge_days) > 0:
        cutoff = (datetime.now() - timedelta(days=int(purge_days))).strftime("%Y-%m-%d %H:%M:%S")
        conn = get_db()
        c = conn.cursor()
        c.execute("DELETE FROM logs WHERE timestamp < ?", (cutoff,))
        conn.commit()
        conn.close()

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS workers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    worker_id TEXT UNIQUE,
                    name TEXT,
                    cin TEXT,
                    phone TEXT,
                    card_uid TEXT UNIQUE
                 )''')
    c.execute('''CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    worker_id TEXT,
                    card_uid TEXT,
                    action TEXT,
                    timestamp DATETIME
                 )''')
    c.execute('''CREATE TABLE IF NOT EXISTS joker_cards (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    card_uid TEXT UNIQUE,
                    label TEXT
                 )''')
    c.execute('''CREATE TABLE IF NOT EXISTS joker_assignments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    joker_uid TEXT,
                    worker_id TEXT,
                    assigned_date TEXT
                 )''')
    conn.commit()
    conn.close()

init_db()