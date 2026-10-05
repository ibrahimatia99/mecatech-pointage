import json
import os
import platform
import sqlite3
import sys
import shutil
import threading
from pathlib import Path
from datetime import datetime, timedelta

APP_NAME = "MecatechPointage"
CONFIG_FILENAME = "config.json"

_DISCOVERY_LOCK = threading.Lock()
_DISCOVERY_DONE = False
_CONFIG_LOCK = threading.RLock()
_DB_PRAGMA_LOCK = threading.Lock()
_WAL_CONFIGURED = set()
_PURGE_LOCK = threading.Lock()
_LAST_PURGE_MONOTONIC = 0.0


def get_app_data_dir():
    """Return a writable per-user directory for application data."""
    system = platform.system()
    if system == "Windows":
        root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
        return os.path.join(root, APP_NAME)
    if system == "Darwin":
        return os.path.expanduser("~/Library/Application Support/" + APP_NAME)
    return os.path.expanduser("~/.local/share/" + APP_NAME)


def get_default_db_dir():
    return os.path.join(get_app_data_dir(), "data")


def get_config_file():
    return os.path.join(get_app_data_dir(), CONFIG_FILENAME)


def _default_config():
    return {
        "db_path": get_default_db_dir(),
        "app_name": "Mecatech Pointage",
        "app_logo": "/static/uploads/logo_icon.png",
        "app_icon": "/static/uploads/icon_icon.png",
        "app_password": "admin",
        "theme": "light",
        "language": "en",
        "primary_color": "#ff5a00",
        "purge_days": 0,
        "auto_checkout_enabled": False,
        "auto_checkout_trigger_time": "20:00",
        "auto_checkout_time": "18:00",
        "work_start_time": "08:00",
        "late_after_time": "08:10",
        "work_end_time": "17:00",
        "expected_daily_hours": 8,
        "weekend_days": [5, 6],
    }


def load_config():
    default_config = _default_config()
    config_file = get_config_file()
    os.makedirs(os.path.dirname(config_file), exist_ok=True)
    if os.path.exists(config_file):
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            if isinstance(cfg, dict):
                default_config.update(cfg)
        except (OSError, ValueError, TypeError):
            # Preserve a broken configuration for diagnostics instead of silently
            # discarding it and writing defaults over the user's settings.
            try:
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                os.replace(config_file, config_file + f".corrupt-{stamp}")
            except OSError:
                pass
    if not default_config.get("db_path"):
        default_config["db_path"] = get_default_db_dir()
    return default_config


def save_config(cfg):
    """Atomically persist configuration while serializing concurrent writers."""
    config_file = get_config_file()
    os.makedirs(os.path.dirname(config_file), exist_ok=True)
    with _CONFIG_LOCK:
        temp_file = config_file + f".{os.getpid()}.tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_file, config_file)



def _database_has_records(path):
    """Return True when a candidate DB is readable and contains application data."""
    try:
        conn = sqlite3.connect(path, timeout=3)
        try:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            if 'workers' not in tables or 'logs' not in tables:
                return False
            row = conn.execute("PRAGMA integrity_check").fetchone()
            if not row or str(row[0]).lower() != 'ok':
                return False
            workers = conn.execute("SELECT COUNT(*) FROM workers").fetchone()[0]
            logs = conn.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
            return bool(workers or logs)
        finally:
            conn.close()
    except Exception:
        return False


def _candidate_database_files():
    """Find portable/demo databases next to the source or executable.

    Discovery is intentionally one-time per process. A populated configured database
    is never replaced, and an existing empty database is never overwritten.
    """
    roots = []
    if getattr(sys, 'frozen', False):
        roots.extend([Path(sys.executable).resolve().parent])
    roots.extend([Path(__file__).resolve().parent, Path.cwd()])
    result = []
    seen = set()
    for root in roots:
        for rel in (
            Path('attendance.db'),
            Path('attendance_demo.db'),
            Path('data') / 'attendance.db',
            Path('demo_data') / 'attendance.db',
            Path('demo_data') / 'attendance_demo.db',
        ):
            candidate = (root / rel).resolve()
            if candidate.exists() and candidate.is_file() and candidate not in seen:
                seen.add(candidate)
                result.append(candidate)
    return result


def _autodiscover_database():
    """Adopt a nearby database only when the configured DB file is absent.

    This keeps demo/test convenience without risking an intentional empty database
    being silently replaced on a later request.
    """
    global _DISCOVERY_DONE
    if _DISCOVERY_DONE:
        return
    with _DISCOVERY_LOCK:
        if _DISCOVERY_DONE:
            return
        cfg = load_config()
        configured_dir = Path(os.path.abspath(os.path.expanduser(cfg.get('db_path') or get_default_db_dir())))
        configured_dir.mkdir(parents=True, exist_ok=True)
        target = (configured_dir / 'attendance.db').resolve()

        candidates = _candidate_database_files()
        target_has_records = target.exists() and _database_has_records(str(target))
        for candidate in candidates:
            if candidate == target or not _database_has_records(str(candidate)):
                continue
            candidate_is_demo = 'demo' in candidate.name.lower() or candidate.parent.name.lower() == 'demo_data'
            # A deliberate demo database may replace a brand-new/empty runtime DB.
            # A normal populated runtime DB is never overwritten automatically.
            should_adopt = (not target.exists()) or (not target_has_records and candidate_is_demo)
            if not should_adopt:
                continue
            try:
                shutil.copy2(candidate, target)
                break
            except OSError:
                continue
        _DISCOVERY_DONE = True


def get_db():
    _autodiscover_database()
    cfg = load_config()
    db_dir = os.path.abspath(os.path.expanduser(cfg.get("db_path") or get_default_db_dir()))
    os.makedirs(db_dir, exist_ok=True)
    db_file = os.path.join(db_dir, "attendance.db")
    conn = sqlite3.connect(db_file, timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    # journal_mode=WAL changes persistent DB state and can briefly require a write
    # lock. Configure it once per DB path rather than on every request.
    db_key = os.path.abspath(db_file)
    if db_key not in _WAL_CONFIGURED:
        with _DB_PRAGMA_LOCK:
            if db_key not in _WAL_CONFIGURED:
                conn.execute("PRAGMA journal_mode = WAL")
                conn.execute("PRAGMA synchronous = NORMAL")
                _WAL_CONFIGURED.add(db_key)
    else:
        conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def init_db():
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        c.execute("""CREATE TABLE IF NOT EXISTS workers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worker_id TEXT UNIQUE,
            name TEXT NOT NULL,
            cin TEXT,
            phone TEXT,
            card_uid TEXT UNIQUE
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worker_id TEXT NOT NULL,
            card_uid TEXT,
            action TEXT NOT NULL,
            timestamp DATETIME NOT NULL
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS joker_cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_uid TEXT UNIQUE,
            label TEXT NOT NULL
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS joker_assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            joker_uid TEXT NOT NULL,
            worker_id TEXT NOT NULL,
            assigned_date TEXT NOT NULL
        )""")
        # Indexes are essential once attendance history grows beyond a few thousand punches.
        c.execute("CREATE INDEX IF NOT EXISTS idx_logs_worker_timestamp ON logs(worker_id, timestamp DESC, id DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs(timestamp)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_logs_action_timestamp ON logs(action, timestamp)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_joker_assignments_uid_date ON joker_assignments(joker_uid, assigned_date)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_joker_assignments_worker_date ON joker_assignments(worker_id, assigned_date)")
        c.execute("""CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            actor TEXT NOT NULL DEFAULT 'admin',
            action TEXT NOT NULL,
            entity_type TEXT,
            entity_id TEXT,
            details TEXT
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp DESC, id DESC)")
        c.execute("""CREATE TABLE IF NOT EXISTS leaves (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worker_id TEXT NOT NULL,
            leave_type TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            note TEXT,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_leaves_worker_dates ON leaves(worker_id, start_date, end_date)")
        c.execute("INSERT OR REPLACE INTO schema_meta(key, value) VALUES('schema_version', '4')")
        conn.commit()
    finally:
        conn.close()


def backup_database(max_backups=7):
    """Create a consistent SQLite backup and retain the newest backups."""
    cfg = load_config()
    db_dir = os.path.abspath(os.path.expanduser(cfg.get("db_path") or get_default_db_dir()))
    db_file = os.path.join(db_dir, "attendance.db")
    if not os.path.exists(db_file):
        return None
    backup_dir = os.path.join(db_dir, "backups")
    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    target = os.path.join(backup_dir, f"attendance_{stamp}.db")
    source = sqlite3.connect(db_file, timeout=15)
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    backups = sorted(
        (os.path.join(backup_dir, name) for name in os.listdir(backup_dir) if name.startswith("attendance_") and name.endswith(".db")),
        key=lambda path: os.path.getmtime(path),
        reverse=True,
    )
    for old in backups[max_backups:]:
        try:
            os.remove(old)
        except OSError:
            pass
    return target


def purge_old_logs():
    global _LAST_PURGE_MONOTONIC
    with _PURGE_LOCK:
        now_mono = __import__('time').monotonic()
        # Purge is maintenance work; ESP heartbeats must not run it every few seconds.
        if now_mono - _LAST_PURGE_MONOTONIC < 300.0:
            return
        _LAST_PURGE_MONOTONIC = now_mono
    cfg = load_config()
    try:
        purge_days = int(cfg.get("purge_days", 0))
    except (TypeError, ValueError):
        purge_days = 0
    if purge_days <= 0:
        return
    cutoff = (datetime.now() - timedelta(days=purge_days)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    try:
        conn.execute("""
            DELETE FROM logs
            WHERE timestamp < ?
              AND NOT (
                action = 'IN'
                AND id = (
                    SELECT l2.id FROM logs l2
                    WHERE l2.worker_id = logs.worker_id
                    ORDER BY l2.timestamp DESC, l2.id DESC
                    LIMIT 1
                )
              )
        """, (cutoff,))
        conn.commit()
    finally:
        conn.close()


def insert_audit(conn, action, entity_type=None, entity_id=None, details=None, actor="admin"):
    """Insert an audit event into an existing transaction/connection."""
    conn.execute(
        "INSERT INTO audit_log(timestamp, actor, action, entity_type, entity_id, details) VALUES (?, ?, ?, ?, ?, ?)",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), str(actor or "admin")[:80], str(action)[:120],
         str(entity_type)[:80] if entity_type else None, str(entity_id)[:120] if entity_id else None,
         str(details)[:1000] if details else None)
    )


def write_audit(action, entity_type=None, entity_id=None, details=None, actor="admin"):
    """Append an audit event using a short independent transaction."""
    conn = get_db()
    try:
        insert_audit(conn, action, entity_type, entity_id, details, actor)
        conn.commit()
    finally:
        conn.close()


def list_backups():
    cfg = load_config()
    db_dir = os.path.abspath(os.path.expanduser(cfg.get("db_path") or get_default_db_dir()))
    backup_dir = os.path.join(db_dir, "backups")
    os.makedirs(backup_dir, exist_ok=True)
    items = []
    for name in sorted(os.listdir(backup_dir), reverse=True):
        if not (name.startswith("attendance_") and name.endswith(".db")):
            continue
        path = os.path.join(backup_dir, name)
        try:
            items.append({"name": name, "size": os.path.getsize(path), "modified": datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M:%S")})
        except OSError:
            pass
    return items


def restore_database(source_path):
    """Validate and restore a SQLite DB atomically-ish with a pre-restore backup."""
    import shutil
    cfg = load_config()
    db_dir = os.path.abspath(os.path.expanduser(cfg.get("db_path") or get_default_db_dir()))
    os.makedirs(db_dir, exist_ok=True)
    db_file = os.path.join(db_dir, "attendance.db")
    source_path = os.path.abspath(source_path)
    if not os.path.isfile(source_path):
        raise FileNotFoundError("Backup file not found")
    test = sqlite3.connect(source_path)
    try:
        row = test.execute("PRAGMA integrity_check").fetchone()
        if not row or str(row[0]).lower() != "ok":
            raise ValueError("The selected database failed SQLite integrity check.")
        required = {"workers", "logs", "joker_cards", "joker_assignments"}
        found = {r[0] for r in test.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if not required.issubset(found):
            raise ValueError("The selected database is not a compatible Mecatech Pointage database.")
    finally:
        test.close()
    backup_database()
    temp_path = db_file + ".restore.tmp"
    shutil.copy2(source_path, temp_path)
    os.replace(temp_path, db_file)
    for suffix in ('-wal', '-shm'):
        try:
            os.remove(db_file + suffix)
        except OSError:
            pass
    _WAL_CONFIGURED.discard(os.path.abspath(db_file))
    init_db()
    return db_file
