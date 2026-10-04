from flask import Blueprint, request, jsonify, render_template
from datetime import datetime, timedelta
import re
import threading
import secrets
from db import get_db, load_config, save_config, purge_old_logs, write_audit, insert_audit

api_bp = Blueprint('api', __name__)

LAST_ESP32_HEARTBEAT = None
STATE_LOCK = threading.RLock()
_LAST_AUTO_CHECKOUT_MONOTONIC = 0.0


def _clean_uid(value):
    if not isinstance(value, str):
        return ""
    value = re.sub(r"[^0-9A-Fa-f]", "", value).upper()
    return value[:32]


def _clean_text(value, max_len=120):
    if value is None:
        return ""
    return str(value).strip()[:max_len]


def _generate_worker_id(conn):
    """Generate a collision-resistant local worker ID when none is supplied."""
    for _ in range(20):
        candidate = 'W' + secrets.token_hex(4).upper()
        if not conn.execute("SELECT 1 FROM workers WHERE worker_id=?", (candidate,)).fetchone():
            return candidate
    raise RuntimeError('Unable to generate a unique worker ID.')


def _as_bool(value):
    if isinstance(value, bool):
        return value
    return str(value or '').strip().lower() in {'1', 'true', 'yes', 'on'}


def _parse_hhmm(value, default):
    try:
        return datetime.strptime(str(value), "%H:%M").time()
    except (TypeError, ValueError):
        return datetime.strptime(default, "%H:%M").time()


def _parse_iso_date(value, field_name):
    value = _clean_text(value, 10)
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        raise ValueError(f'Invalid {field_name}. Use YYYY-MM-DD.')


def process_auto_checkouts(now=None):
    global _LAST_AUTO_CHECKOUT_MONOTONIC
    # Heartbeat traffic may be much more frequent than the maintenance interval.
    # Keep the existing ESP endpoint untouched, while preventing redundant DB scans.
    if now is None:
        current = __import__('time').monotonic()
        if current - _LAST_AUTO_CHECKOUT_MONOTONIC < 4.0:
            return 0
        _LAST_AUTO_CHECKOUT_MONOTONIC = current
    with STATE_LOCK:
        return _process_auto_checkouts(now)


def _process_auto_checkouts(now=None):
    """Recover forgotten OUT punches without requiring ESP32 communication.

    The scheduler may run late, the app may have been restarted, or the
    terminal may have been disconnected. For every worker whose latest punch
    is still IN, close the open attendance on that punch's own date when the
    configured checkout time has elapsed. Today's punch is only closed after
    the configured trigger time.
    """
    cfg = load_config()
    if not _as_bool(cfg.get("auto_checkout_enabled", False)):
        return 0

    now = now or datetime.now()
    trigger_time = _parse_hhmm(cfg.get("auto_checkout_trigger_time"), "20:00")
    checkout_time = _parse_hhmm(cfg.get("auto_checkout_time"), "18:00")

    # For today's records, the trigger controls when automatic closure runs.
    # The checkout timestamp itself must not be in the future.
    today = now.date()
    today_checkout = datetime.combine(today, checkout_time)
    if now.time() < trigger_time or today_checkout > now:
        today_is_due = False
    else:
        today_is_due = True

    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("""
            SELECT w.worker_id, latest.action, latest.timestamp
            FROM workers w
            JOIN logs latest ON latest.id = (
                SELECT l2.id
                FROM logs l2
                WHERE l2.worker_id = w.worker_id
                ORDER BY l2.timestamp DESC, l2.id DESC
                LIMIT 1
            )
            WHERE latest.action = 'IN'
        """)
        open_workers = c.fetchall()

        count = 0
        for row in open_workers:
            worker_id = row["worker_id"]
            raw_last_in = row["timestamp"]
            try:
                last_in_dt = datetime.strptime(raw_last_in, "%Y-%m-%d %H:%M:%S")
            except (TypeError, ValueError):
                continue

            log_date = last_in_dt.date()
            checkout_dt = datetime.combine(log_date, checkout_time)

            if log_date == today:
                # Today is only eligible after the trigger time.
                if not today_is_due:
                    continue
            else:
                # A missed previous-day checkout is overdue as soon as the app
                # comes back, so it can be recovered without an ESP heartbeat.
                if checkout_dt > now:
                    continue

            # Never create an OUT before the IN that it closes.
            if last_in_dt >= checkout_dt:
                continue

            checkout_timestamp = checkout_dt.strftime("%Y-%m-%d %H:%M:%S")

            # Idempotent recovery: the same automatic OUT can never be added twice.
            c.execute("""
                SELECT 1 FROM logs
                WHERE worker_id = ? AND action = 'OUT' AND timestamp = ?
                LIMIT 1
            """, (worker_id, checkout_timestamp))
            if c.fetchone():
                continue

            c.execute("""
                INSERT INTO logs (worker_id, card_uid, action, timestamp)
                VALUES (?, ?, 'OUT', ?)
            """, (worker_id, "AUTO_CHECKOUT", checkout_timestamp))
            count += 1

        conn.commit()
        return count
    finally:
        conn.close()


# Card Enrollment State
ENROLL_STATE = "idle"  # "idle", "waiting", "success"
ENROLL_WORKER_ID = None
ENROLL_WORKER_NAME = ""
ENROLL_SCANNED_UID = ""

# Joker Card Enrollment State
JOKER_ENROLL_STATE = "idle"  # "idle", "waiting", "success", "error"
JOKER_ENROLL_LABEL = "Joker Card"
JOKER_SCANNED_UID = ""
JOKER_ENROLL_ERROR = ""

# Temporary Spare ("Joker") Card State
SPARE_PENDING = False
SPARE_CARD_UID = ""

@api_bp.route('/heartbeat', methods=['POST'])
def heartbeat():
    global LAST_ESP32_HEARTBEAT
    LAST_ESP32_HEARTBEAT = datetime.now()
    process_auto_checkouts()
    purge_old_logs()
    return jsonify({"status": "ok"}), 200

# --- WORKER CARD ENROLLMENT ROUTES ---
@api_bp.route('/enroll/start', methods=['POST'])
def start_enroll():
    global ENROLL_STATE, ENROLL_WORKER_ID, ENROLL_WORKER_NAME, ENROLL_SCANNED_UID
    data = request.json or {}
    worker_id = _clean_text(data.get('worker_id'), 64)
    
    if not worker_id:
        return jsonify({"status": "error", "message": "Missing worker ID"}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT name FROM workers WHERE worker_id = ?", (worker_id,))
    row = c.fetchone()
    conn.close()
    
    if not row:
        return jsonify({"status": "error", "message": "Worker not found"}), 404
        
    ENROLL_WORKER_ID = worker_id
    ENROLL_WORKER_NAME = row['name']
    ENROLL_STATE = "waiting"
    ENROLL_SCANNED_UID = ""
    return jsonify({"status": "success", "message": "Ready for card tap"})

@api_bp.route('/enroll/status', methods=['GET'])
def enroll_status():
    return jsonify({
        "state": ENROLL_STATE,
        "worker_id": ENROLL_WORKER_ID,
        "worker_name": ENROLL_WORKER_NAME,
        "card_uid": ENROLL_SCANNED_UID
    })

@api_bp.route('/enroll/cancel', methods=['POST'])
def cancel_enroll():
    global ENROLL_STATE, ENROLL_WORKER_ID, ENROLL_WORKER_NAME, ENROLL_SCANNED_UID
    ENROLL_STATE = "idle"
    ENROLL_WORKER_ID = None
    ENROLL_WORKER_NAME = ""
    ENROLL_SCANNED_UID = ""
    return jsonify({"status": "cancelled"})

# --- JOKER CARD ENROLLMENT & MANAGEMENT ROUTES ---
@api_bp.route('/joker/enroll/start', methods=['POST'])
def start_joker_enroll():
    global JOKER_ENROLL_STATE, JOKER_ENROLL_LABEL, JOKER_SCANNED_UID, JOKER_ENROLL_ERROR
    data = request.json or {}
    JOKER_ENROLL_LABEL = _clean_text(data.get('label') or 'Joker Card', 80) or 'Joker Card'
    JOKER_ENROLL_STATE = "waiting"
    JOKER_SCANNED_UID = ""
    JOKER_ENROLL_ERROR = ""
    return jsonify({"status": "success", "message": "Ready to scan Joker card"})

@api_bp.route('/joker/enroll/status', methods=['GET'])
def joker_enroll_status():
    return jsonify({
        "state": JOKER_ENROLL_STATE,
        "label": JOKER_ENROLL_LABEL,
        "card_uid": JOKER_SCANNED_UID,
        "error": JOKER_ENROLL_ERROR
    })

@api_bp.route('/joker/enroll/cancel', methods=['POST'])
def cancel_joker_enroll():
    global JOKER_ENROLL_STATE, JOKER_ENROLL_LABEL, JOKER_SCANNED_UID, JOKER_ENROLL_ERROR
    JOKER_ENROLL_STATE = "idle"
    JOKER_ENROLL_LABEL = "Joker Card"
    JOKER_SCANNED_UID = ""
    JOKER_ENROLL_ERROR = ""
    return jsonify({"status": "cancelled"})

@api_bp.route('/joker/list', methods=['GET'])
def list_joker_cards():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM joker_cards ORDER BY id DESC")
    cards = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify({"joker_cards": cards})

@api_bp.route('/joker/delete/<int:joker_id>', methods=['DELETE'])
def delete_joker_card(joker_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM joker_cards WHERE id = ?", (joker_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "message": "Joker card deleted"}), 200

# --- JOKER CARD SCAN RESOLUTION ---
@api_bp.route('/spare/status', methods=['GET'])
def spare_status():
    return jsonify({
        "pending": SPARE_PENDING,
        "card_uid": SPARE_CARD_UID
    })

@api_bp.route('/spare/resolve', methods=['POST'])
def spare_resolve():
    global SPARE_PENDING, SPARE_CARD_UID
    data = request.json or {}
    worker_id = data.get('worker_id')
    
    if not worker_id or not SPARE_PENDING:
        return jsonify({"status": "error", "message": "No active spare card operation"}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT name FROM workers WHERE worker_id = ?", (worker_id,))
    worker = c.fetchone()
    
    if not worker:
        conn.close()
        return jsonify({"status": "error", "message": "Worker not found"}), 404

    # Determine alternating IN/OUT action
    c.execute("SELECT action FROM logs WHERE worker_id = ? ORDER BY timestamp DESC LIMIT 1", (worker_id,))
    last_log = c.fetchone()
    new_action = "OUT" if (last_log and last_log['action'] == "IN") else "IN"
    now_dt = datetime.now()
    now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    today_str = now_dt.strftime("%Y-%m-%d")

    # Record attendance punch log
    c.execute("INSERT INTO logs (worker_id, card_uid, action, timestamp) VALUES (?, ?, ?, ?)",
              (worker_id, SPARE_CARD_UID, new_action, now_str))

    # Link joker card to worker for today
    c.execute("DELETE FROM joker_assignments WHERE joker_uid = ?", (SPARE_CARD_UID,))
    c.execute("INSERT INTO joker_assignments (joker_uid, worker_id, assigned_date) VALUES (?, ?, ?)",
              (SPARE_CARD_UID, worker_id, today_str))

    conn.commit()
    conn.close()

    resolved_uid = SPARE_CARD_UID
    SPARE_PENDING = False
    SPARE_CARD_UID = ""

    return jsonify({
        "status": "success", 
        "worker_name": worker['name'], 
        "action": new_action, 
        "card_uid": resolved_uid
    }), 200

@api_bp.route('/spare/dismiss', methods=['POST'])
def spare_dismiss():
    global SPARE_PENDING, SPARE_CARD_UID
    SPARE_PENDING = False
    SPARE_CARD_UID = ""
    return jsonify({"status": "dismissed"}), 200

# --- CARD SCAN ROUTE ---
@api_bp.route('/scan', methods=['POST'])
def api_scan():
    with STATE_LOCK:
        return _api_scan()


def _api_scan():
    global LAST_ESP32_HEARTBEAT, ENROLL_STATE, ENROLL_WORKER_ID, ENROLL_WORKER_NAME, ENROLL_SCANNED_UID
    global JOKER_ENROLL_STATE, JOKER_ENROLL_LABEL, JOKER_SCANNED_UID, JOKER_ENROLL_ERROR
    global SPARE_PENDING, SPARE_CARD_UID
    
    LAST_ESP32_HEARTBEAT = datetime.now()
    data = request.json or {}
    uid = _clean_uid(data.get('card_uid'))

    if not uid:
        return jsonify({"status": "error", "message": "Missing card UID"}), 400

    conn = get_db()
    c = conn.cursor()
    today_str = datetime.now().strftime("%Y-%m-%d")

    # 1. WORKER CARD ENROLLMENT WORKFLOW
    if ENROLL_STATE == "waiting" and ENROLL_WORKER_ID:
        c.execute("SELECT name FROM workers WHERE card_uid = ?", (uid,))
        existing = c.fetchone()
        if existing:
            conn.close()
            return jsonify({"status": "error", "message": f"Card already assigned to {existing['name']}"}), 400

        c.execute("UPDATE workers SET card_uid = ? WHERE worker_id = ?", (uid, ENROLL_WORKER_ID))
        conn.commit()
        conn.close()
        
        ENROLL_STATE = "success"
        ENROLL_SCANNED_UID = uid
        return jsonify({"status": "success", "message": "Card assigned successfully"}), 200

    # 2. JOKER CARD ENROLLMENT WORKFLOW
    if JOKER_ENROLL_STATE == "waiting":
        c.execute("SELECT name FROM workers WHERE card_uid = ?", (uid,))
        existing_worker = c.fetchone()
        if existing_worker:
            conn.close()
            JOKER_ENROLL_STATE = "error"
            JOKER_ENROLL_ERROR = f"Card already assigned to worker {existing_worker['name']}"
            return jsonify({"status": "error", "message": JOKER_ENROLL_ERROR}), 400

        c.execute("SELECT label FROM joker_cards WHERE card_uid = ?", (uid,))
        existing_joker = c.fetchone()
        if existing_joker:
            conn.close()
            JOKER_ENROLL_STATE = "error"
            JOKER_ENROLL_ERROR = "Card is already registered as a Joker card"
            return jsonify({"status": "error", "message": JOKER_ENROLL_ERROR}), 400

        try:
            c.execute("INSERT INTO joker_cards (card_uid, label) VALUES (?, ?)", (uid, JOKER_ENROLL_LABEL))
            conn.commit()
            conn.close()
            JOKER_ENROLL_STATE = "success"
            JOKER_SCANNED_UID = uid
            return jsonify({"status": "success", "message": "Joker card added successfully"}), 200
        except Exception as e:
            conn.close()
            JOKER_ENROLL_STATE = "error"
            JOKER_ENROLL_ERROR = str(e)
            return jsonify({"status": "error", "message": str(e)}), 400

    # 3. CHECK IF REGISTERED JOKER CARD
    c.execute("SELECT * FROM joker_cards WHERE card_uid = ?", (uid,))
    joker = c.fetchone()

    if joker:
        # Check if joker card is assigned to a worker for today
        c.execute("SELECT worker_id FROM joker_assignments WHERE joker_uid = ? AND assigned_date = ?", (uid, today_str))
        assignment = c.fetchone()

        if assignment:
            # Active assignment for today -> auto log punch for assigned worker
            worker_id = assignment['worker_id']
            c.execute("SELECT name FROM workers WHERE worker_id = ?", (worker_id,))
            worker = c.fetchone()

            if worker:
                c.execute("SELECT action FROM logs WHERE worker_id = ? ORDER BY timestamp DESC LIMIT 1", (worker_id,))
                last_log = c.fetchone()
                new_action = "OUT" if (last_log and last_log['action'] == "IN") else "IN"
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                c.execute("INSERT INTO logs (worker_id, card_uid, action, timestamp) VALUES (?, ?, ?, ?)",
                          (worker_id, uid, new_action, now_str))
                conn.commit()
                conn.close()
                return jsonify({
                    "status": "success", 
                    "action": new_action, 
                    "worker_name": worker['name'],
                    "message": "Logged via Joker Card"
                }), 200

        # No active assignment for today -> trigger Joker popup modal
        conn.close()
        SPARE_PENDING = True
        SPARE_CARD_UID = uid
        return jsonify({
            "status": "spare_pending", 
            "message": "Joker card detected. Select worker.", 
            "card_uid": uid
        }), 202

    # 4. CHECK IF REGISTERED WORKER MAIN CARD
    c.execute("SELECT worker_id, name FROM workers WHERE card_uid = ?", (uid,))
    worker = c.fetchone()
    
    if worker:
        worker_id, name = worker['worker_id'], worker['name']
        
        # Worker scanned their main card -> stop/clear any active Joker card assigned to this worker today
        c.execute("DELETE FROM joker_assignments WHERE worker_id = ?", (worker_id,))

        c.execute("SELECT action FROM logs WHERE worker_id = ? ORDER BY timestamp DESC LIMIT 1", (worker_id,))
        last_log = c.fetchone()
        
        new_action = "OUT" if (last_log and last_log['action'] == "IN") else "IN"
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        c.execute("INSERT INTO logs (worker_id, card_uid, action, timestamp) VALUES (?, ?, ?, ?)",
                  (worker_id, uid, new_action, now_str))
        conn.commit()
        conn.close()
        
        return jsonify({"status": "success", "action": new_action, "worker_name": name}), 200

    # 5. UNREGISTERED CARD
    conn.close()
    return jsonify({"status": "error", "message": "Unregistered card scanned"}), 400

# --- ATTENDANCE BUSINESS RULE HELPERS ---
def _is_weekend(day, cfg=None):
    cfg = cfg or load_config()
    try:
        weekend = set(int(x) for x in (cfg.get('weekend_days') or [5, 6]))
    except (TypeError, ValueError):
        weekend = {5, 6}
    return day.weekday() in weekend


def _worker_leave_for_day(conn, worker_id, day):
    row = conn.execute(
        "SELECT id, leave_type, note FROM leaves WHERE worker_id = ? AND start_date <= ? AND end_date >= ? ORDER BY id DESC LIMIT 1",
        (worker_id, day.isoformat(), day.isoformat())
    ).fetchone()
    return dict(row) if row else None


def _duration_seconds_for_logs(logs, now=None, open_end=None):
    now = now or datetime.now()
    total = 0
    open_since = None
    for row in logs:
        action = str(row['action']).upper()
        try:
            ts = datetime.strptime(row['timestamp'], '%Y-%m-%d %H:%M:%S')
        except (TypeError, ValueError):
            continue
        if action == 'IN':
            # Ignore duplicate IN punches rather than discarding the original open interval.
            if open_since is None:
                open_since = ts
        elif action == 'OUT' and open_since is not None:
            delta = (ts - open_since).total_seconds()
            if delta > 0:
                total += delta
            open_since = None
    if open_since:
        effective_end = now
        if open_end is not None and open_end < effective_end:
            effective_end = open_end
        delta = (effective_end - open_since).total_seconds()
        if delta > 0:
            total += delta
    return int(total)


def _first_in_today(logs):
    for row in logs:
        if row['action'] == 'IN':
            return row
    return None


def _format_duration(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    return f'{h}h {m:02d}m'


def _late_minutes(timestamp, cfg=None):
    cfg = cfg or load_config()
    threshold = _parse_hhmm(cfg.get('late_after_time'), '08:10')
    try:
        ts = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
    except (TypeError, ValueError):
        return 0
    threshold_dt = datetime.combine(ts.date(), threshold)
    return max(0, int((ts - threshold_dt).total_seconds() // 60))


# --- DASHBOARD & WORKER MANAGEMENT ---
@api_bp.route('/dashboard', methods=['GET'])
def get_dashboard():
    cfg = load_config()
    now = datetime.now()
    today = now.date()
    conn = get_db()
    try:
        workers = [dict(row) for row in conn.execute("SELECT * FROM workers ORDER BY name COLLATE NOCASE").fetchall()]
        today_logs = {}
        for w in workers:
            rows = [dict(r) for r in conn.execute(
                "SELECT id, action, timestamp FROM logs WHERE worker_id = ? AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp ASC, id ASC",
                (w['worker_id'], f'{today.isoformat()} 00:00:00', f'{today.isoformat()} 23:59:59')
            ).fetchall()]
            today_logs[w['worker_id']] = rows
            last = conn.execute(
                "SELECT action, timestamp FROM logs WHERE worker_id = ? ORDER BY timestamp DESC, id DESC LIMIT 1",
                (w['worker_id'],)
            ).fetchone()
            leave = _worker_leave_for_day(conn, w['worker_id'], today)
            first_in = _first_in_today(rows)
            late_min = _late_minutes(first_in['timestamp'], cfg) if first_in and not _is_weekend(today, cfg) else 0
            worked = _duration_seconds_for_logs(rows, now=now)
            if leave:
                status = 'LEAVE'
            elif not rows and _is_weekend(today, cfg):
                status = 'WEEKEND'
            elif not rows:
                status = 'ABSENT'
            elif last and last['action'] == 'IN':
                status = 'LATE' if late_min > 0 else 'PRESENT'
            else:
                status = 'CHECKED_OUT'
            w.update({
                'status': status,
                'last_time': last['timestamp'] if last else None,
                'first_in': first_in['timestamp'].split(' ')[1][:5] if first_in else None,
                'last_out': next((r['timestamp'].split(' ')[1][:5] for r in reversed(rows) if r['action']=='OUT'), None),
                'worked_seconds_today': worked,
                'worked_today': _format_duration(worked),
                'late_minutes': late_min,
                'leave': leave,
            })
        statuses = [w['status'] for w in workers]
        stats = {
            'total_workers': len(workers),
            'present_now': sum(s in {'PRESENT','LATE'} for s in statuses),
            'checked_out_today': statuses.count('CHECKED_OUT'),
            'absent_today': statuses.count('ABSENT'),
            'late_today': statuses.count('LATE'),
            'on_leave': statuses.count('LEAVE'),
            'weekend_today': _is_weekend(today, cfg),
        }
    finally:
        conn.close()
    online = bool(LAST_ESP32_HEARTBEAT and (datetime.now() - LAST_ESP32_HEARTBEAT).total_seconds() < 10)
    return jsonify({'workers': workers, 'stats': stats, 'date': today.isoformat(), 'esp32_online': online, 'settings': {
        'work_start_time': cfg.get('work_start_time','08:00'),
        'late_after_time': cfg.get('late_after_time','08:10'),
        'work_end_time': cfg.get('work_end_time','17:00'),
        'expected_daily_hours': cfg.get('expected_daily_hours',8),
    }})


@api_bp.route('/worker/add', methods=['POST'])
def add_worker():
    data = request.json or {}
    name = _clean_text(data.get('name'), 120)
    if not name:
        return jsonify({"status": "error", "message": "Worker name is required."}), 400

    conn = get_db()
    try:
        requested_id = _clean_text(data.get('worker_id'), 64)
        worker_id = requested_id or _generate_worker_id(conn)
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', worker_id):
            return jsonify({"status": "error", "message": "Worker ID contains invalid characters."}), 400
        card_uid = _clean_uid(data.get('card_uid')) or None
        try:
            c = conn.execute("""
                INSERT INTO workers (worker_id, name, cin, phone, card_uid)
                VALUES (?, ?, ?, ?, ?)
            """, (worker_id, name, _clean_text(data.get('cin'), 64), _clean_text(data.get('phone'), 40), card_uid))
            insert_audit(conn, 'worker_added', 'worker', worker_id, f'name={name}')
            conn.commit()
        except Exception as exc:
            conn.rollback()
            message = 'Worker already exists or card UID is already assigned.' if 'UNIQUE constraint failed' in str(exc) else str(exc)
            return jsonify({"status": "error", "message": message}), 400
    finally:
        conn.close()
    return jsonify({"status": "success", "worker_id": worker_id}), 200

@api_bp.route('/worker/update', methods=['PUT'])
def update_worker():
    data = request.json or {}
    worker_id = _clean_text(data.get('worker_id'), 64)
    name = _clean_text(data.get('name'), 120)
    if not worker_id or not name:
        return jsonify({"status": "error", "message": "Worker ID and name are required."}), 400
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("""
            UPDATE workers SET name = ?, cin = ?, phone = ? WHERE worker_id = ?
        """, (name, _clean_text(data.get('cin'), 64), _clean_text(data.get('phone'), 40), worker_id))
        if c.rowcount == 0:
            return jsonify({"status":"error","message":"Worker not found."}),404
        insert_audit(conn, 'worker_updated', 'worker', worker_id, f'name={name}')
        conn.commit()
        return jsonify({"status": "success"}), 200
    except Exception as exc:
        conn.rollback()
        return jsonify({"status": "error", "message": str(exc)}), 400
    finally:
        conn.close()

@api_bp.route('/worker/delete/<worker_id>', methods=['DELETE'])
def delete_worker(worker_id):
    conn = get_db()
    try:
        c = conn.cursor()
        worker = c.execute("SELECT name FROM workers WHERE worker_id = ?", (worker_id,)).fetchone()
        if not worker:
            return jsonify({"status":"error","message":"Worker not found."}),404
        c.execute("DELETE FROM leaves WHERE worker_id = ?", (worker_id,))
        c.execute("DELETE FROM logs WHERE worker_id = ?", (worker_id,))
        c.execute("DELETE FROM joker_assignments WHERE worker_id = ?", (worker_id,))
        c.execute("DELETE FROM workers WHERE worker_id = ?", (worker_id,))
        insert_audit(conn, 'worker_deleted', 'worker', worker_id, f"Deleted worker {worker['name']} and related attendance/leave records.")
        conn.commit()
    except Exception as exc:
        conn.rollback()
        return jsonify({"status":"error","message":str(exc)}),500
    finally:
        conn.close()
    return jsonify({"status": "deleted"}), 200

# --- ATTENDANCE REPORTING ENGINE ---
@api_bp.route('/worker/history/<worker_id>', methods=['GET'])
def get_history(worker_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM workers WHERE worker_id = ?", (worker_id,))
    worker = c.fetchone()
    if not worker:
        conn.close()
        return jsonify({'status':'error','message':'Worker not found.'}),404

    start_param = request.args.get('start_date')
    end_param = request.args.get('end_date')
    try:
        start_date = _parse_iso_date(start_param, 'start date') if start_param else None
        end_date = _parse_iso_date(end_param, 'end date') if end_param else None
    except ValueError as exc:
        conn.close()
        return jsonify({'status':'error','message':str(exc)}), 400
    if start_date and end_date and start_date > end_date:
        conn.close()
        return jsonify({'status':'error','message':'Start date cannot be after end date.'}), 400

    query = "SELECT id, action, timestamp FROM logs WHERE worker_id = ?"
    params = [worker_id]

    if start_date:
        query += " AND timestamp >= ?"
        params.append(f"{start_date.isoformat()} 00:00:00")
    if end_date:
        query += " AND timestamp <= ?"
        params.append(f"{end_date.isoformat()} 23:59:59")

    query += " ORDER BY timestamp ASC, id ASC"

    c.execute(query, tuple(params))
    logs = [dict(row) for row in c.fetchall()]
    conn.close()

    days_data = {}
    now = datetime.now()
    start_of_week = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    for entry in logs:
        ts = datetime.strptime(entry['timestamp'], "%Y-%m-%d %H:%M:%S")
        day_str = ts.strftime("%A, %b %d, %Y")
        days_data.setdefault(day_str, {"logs": [], "seconds": 0, "first_timestamp": ts})["logs"].append(entry)

    cfg = load_config()
    work_end_time = _parse_hhmm(cfg.get('work_end_time'), '17:00')
    for data in days_data.values():
        day = data['first_timestamp'].date()
        cap = datetime.combine(day, work_end_time) if day < now.date() else None
        data["seconds"] = _duration_seconds_for_logs(data["logs"], now=now, open_end=cap)

    total_filtered_seconds = sum(data["seconds"] for data in days_data.values())
    total_week_seconds = sum(data["seconds"] for data in days_data.values() if data["first_timestamp"] >= start_of_week)
    total_month_seconds = sum(data["seconds"] for data in days_data.values() if data["first_timestamp"] >= start_of_month)

    formatted_days = []
    for day, data in reversed(list(days_data.items())):
        hrs = int(data["seconds"] // 3600)
        mins = int((data["seconds"] % 3600) // 60)
        formatted_days.append({
            "date": day,
            "logs": list(reversed(data["logs"])),
            "total_time": f"{hrs}h {mins}m" if data["seconds"] > 0 else "--"
        })

    def format_total(seconds):
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        return f"{h}h {m}m"

    # Monthly calendar and summary are intentionally computed from local data only.
    calendar_month = (start_param[:7] if start_param else datetime.now().strftime('%Y-%m'))
    y, m = map(int, calendar_month.split('-'))
    month_start = datetime(y, m, 1).date()
    month_end = datetime(y + (1 if m == 12 else 0), 1 if m == 12 else m + 1, 1).date() - timedelta(days=1)
    # Reload through a short-lived connection for monthly/calendar data.
    c2 = get_db()
    all_month_rows = [dict(r) for r in c2.execute("SELECT action, timestamp FROM logs WHERE worker_id=? AND timestamp>=? AND timestamp<=? ORDER BY timestamp ASC, id ASC", (worker_id, f'{month_start.isoformat()} 00:00:00', f'{month_end.isoformat()} 23:59:59')).fetchall()]
    leave_rows = [dict(r) for r in c2.execute("SELECT id, leave_type, start_date, end_date, note FROM leaves WHERE worker_id=? AND start_date<=? AND end_date>=?", (worker_id, month_end.isoformat(), month_start.isoformat())).fetchall()]
    c2.close()
    by_day={}
    for row in all_month_rows:
        by_day.setdefault(row['timestamp'][:10], []).append(row)
    first=month_start
    calendar_days=[]
    present_days=absent_days=late_days=leave_days_count=worked_month=0
    cur=first
    while cur<=month_end:
        iso=cur.isoformat(); leave=next((l for l in leave_rows if l['start_date']<=iso<=l['end_date']), None); rows=by_day.get(iso,[])
        work_end_time = _parse_hhmm(cfg.get('work_end_time'), '17:00')
        open_end = None if cur == datetime.now().date() else datetime.combine(cur, work_end_time)
        worked=_duration_seconds_for_logs(rows, now=datetime.now(), open_end=open_end)
        first_in=next((r for r in rows if r['action']=='IN'), None)
        is_late=bool(first_in and _late_minutes(first_in['timestamp'],cfg)>0 and not _is_weekend(cur,cfg))
        today_date = datetime.now().date()
        if cur > today_date: status='UPCOMING'
        elif leave: status='LEAVE'; leave_days_count+=1
        elif _is_weekend(cur,cfg): status='WEEKEND'
        elif any(r['action']=='IN' for r in rows): status='LATE' if is_late else 'PRESENT'; present_days+=1; late_days+=1 if is_late else 0
        else: status='ABSENT'; absent_days+=1
        worked_month += worked
        calendar_days.append({'iso_date':iso,'status':status,'total_time':_format_duration(worked) if worked else ''})
        cur += timedelta(days=1)
    return jsonify({
        'worker': dict(worker) if worker else {}, 'days': formatted_days,
        'week_total': format_total(total_week_seconds), 'month_total': format_total(total_month_seconds),
        'range_total': format_total(total_filtered_seconds), 'calendar_month': calendar_month, 'calendar_days': calendar_days,
        'leave_days': leave_rows, 'monthly_summary': {'present_days':present_days,'absent_days':absent_days,'late_days':late_days,'leave_days':leave_days_count,'worked':format_total(worked_month)}
    })

@api_bp.route('/worker/log/<int:log_id>', methods=['PUT'])
def update_worker_log(log_id):
    """Correct an attendance record timestamp in the local database only.

    The attendance action (IN/OUT) is immutable from the edit dialog. Operators
    may correct the date/time of the existing event or delete the event.
    Timestamp corrections are intentionally not blocked by adjacency rules.
    """
    data = request.get_json(silent=True) or {}
    timestamp_value = _clean_text(data.get('timestamp'), 32)
    if not timestamp_value:
        return jsonify({"status": "error", "message": "Timestamp is required."}), 400

    parsed = None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            parsed = datetime.strptime(timestamp_value, fmt)
            break
        except ValueError:
            pass
    if parsed is None:
        return jsonify({"status": "error", "message": "Invalid date/time. Use YYYY-MM-DD HH:MM."}), 400

    normalized = parsed.strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    try:
        c = conn.cursor()
        existing = c.execute(
            "SELECT id, worker_id, action, timestamp FROM logs WHERE id = ?",
            (log_id,)
        ).fetchone()
        if not existing:
            return jsonify({"status": "error", "message": "Attendance record not found."}), 404

        reason = _clean_text(data.get('reason'), 300)
        c.execute("UPDATE logs SET timestamp = ? WHERE id = ?", (normalized, log_id))
        insert_audit(
            conn,
            'attendance_time_edited',
            'log',
            log_id,
            f"{existing['timestamp']} -> {normalized}; action={existing['action']}; reason={reason}"
        )
        conn.commit()
        return jsonify({
            "status": "success",
            "log_id": log_id,
            "timestamp": normalized,
            "action": existing['action']
        }), 200
    finally:
        conn.close()

@api_bp.route('/worker/log/<int:log_id>', methods=['DELETE'])
def delete_worker_log(log_id):
    """Delete a single attendance record from the local database only."""
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT id, worker_id, action, timestamp FROM logs WHERE id = ?", (log_id,))
        existing = c.fetchone()
        if not existing:
            return jsonify({"status": "error", "message": "Attendance record not found."}), 404
        c.execute("DELETE FROM logs WHERE id = ?", (log_id,))
        insert_audit(conn, 'attendance_deleted', 'log', log_id, f"{existing['worker_id']}: {existing['timestamp']} {existing['action']}")
        conn.commit()
        return jsonify({"status": "success", "log_id": log_id}), 200
    finally:
        conn.close()

@api_bp.route('/audit', methods=['GET'])
def get_audit_log():
    try:
        limit = max(1, min(500, int(request.args.get('limit', 200))))
    except ValueError:
        limit = 200
    conn = get_db()
    rows = [dict(r) for r in conn.execute("SELECT id, timestamp, actor, action, entity_type, entity_id, details FROM audit_log ORDER BY timestamp DESC, id DESC LIMIT ?", (limit,)).fetchall()]
    conn.close()
    return jsonify({'audit': rows})


@api_bp.route('/leave/list', methods=['GET'])
def list_leaves():
    conn = get_db()
    rows = [dict(r) for r in conn.execute("SELECT l.*, w.name AS worker_name FROM leaves l LEFT JOIN workers w ON w.worker_id=l.worker_id ORDER BY l.start_date DESC, l.id DESC").fetchall()]
    conn.close()
    return jsonify({'leaves': rows})


@api_bp.route('/leave/add', methods=['POST'])
def add_leave():
    data = request.json or {}
    worker_id = _clean_text(data.get('worker_id'), 64)
    leave_type = _clean_text(data.get('leave_type'), 50)
    start_date = _clean_text(data.get('start_date'), 10)
    end_date = _clean_text(data.get('end_date'), 10)
    note = _clean_text(data.get('note'), 300)
    try:
        start = datetime.strptime(start_date, '%Y-%m-%d').date()
        end = datetime.strptime(end_date, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'status':'error','message':'Invalid leave dates.'}), 400
    if not worker_id or not leave_type or end < start:
        return jsonify({'status':'error','message':'Worker, leave type and valid dates are required.'}), 400
    conn = get_db()
    try:
        if not conn.execute("SELECT 1 FROM workers WHERE worker_id=?", (worker_id,)).fetchone():
            return jsonify({'status':'error','message':'Worker not found.'}), 404
        overlap = conn.execute("SELECT 1 FROM leaves WHERE worker_id=? AND start_date<=? AND end_date>=? LIMIT 1", (worker_id, end.isoformat(), start.isoformat())).fetchone()
        if overlap:
            return jsonify({'status':'error','message':'This leave overlaps an existing leave for the same worker.'}), 409
        cur = conn.execute("INSERT INTO leaves(worker_id, leave_type, start_date, end_date, note) VALUES(?,?,?,?,?)", (worker_id, leave_type, start.isoformat(), end.isoformat(), note))
        lid = cur.lastrowid
        insert_audit(conn, 'leave_added', 'leave', lid, f'{worker_id}: {leave_type} {start_date} -> {end_date}')
        conn.commit()
    except Exception as exc:
        conn.rollback()
        return jsonify({'status':'error','message':str(exc)}), 500
    finally:
        conn.close()
    return jsonify({'status':'success','id':lid}), 200


@api_bp.route('/leave/delete/<int:leave_id>', methods=['DELETE'])
def delete_leave(leave_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM leaves WHERE id=?", (leave_id,)).fetchone()
    if not row:
        conn.close(); return jsonify({'status':'error','message':'Leave record not found.'}), 404
    try:
        conn.execute("DELETE FROM leaves WHERE id=?", (leave_id,))
        insert_audit(conn, 'leave_deleted', 'leave', leave_id, f"{row['worker_id']}: {row['leave_type']} {row['start_date']} -> {row['end_date']}")
        conn.commit()
    except Exception as exc:
        conn.rollback()
        conn.close()
        return jsonify({'status':'error','message':str(exc)}), 500
    conn.close()
    return jsonify({'status':'success'}), 200


def _pdf_escape(value):
    """Escape a text value for a simple, dependency-free PDF text object."""
    text = str(value or "").encode("latin-1", "replace").decode("latin-1")
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _build_simple_attendance_pdf(worker_name, worker_id, rows):
    """Build a small, printable attendance PDF without ReportLab/Pillow.

    Keeping PDF generation dependency-free makes the Windows build more
    reliable while preserving the existing local/offline architecture.
    """
    import io

    lines = [
        "Mecatech Pointage",
        "Attendance Report",
        f"Worker: {worker_name}",
        f"Worker ID: {worker_id}",
        "",
        "Date        Time      Action",
        "--------------------------------",
    ]
    for row in rows:
        stamp = row.get("timestamp", "")
        lines.append(f"{stamp[:10]:<12}{stamp[11:16]:<10}{row.get('action', '')}")

    # A4 portrait: 595 x 842 points. Keep a generous top/bottom margin.
    lines_per_page = 46
    pages = [lines[i:i + lines_per_page] for i in range(0, len(lines), lines_per_page)] or [[]]

    objects = {}
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    page_refs = []
    next_obj = 4

    for page_lines in pages:
        content_obj = next_obj
        page_obj = next_obj + 1
        next_obj += 2
        page_refs.append(page_obj)

        content_parts = ["BT", "/F1 10 Tf", "40 800 Td"]
        for idx, line in enumerate(page_lines):
            if idx:
                content_parts.append("0 -16 Td")
            # Keep each line inside the printable width.
            content_parts.append(f"({_pdf_escape(line[:92])}) Tj")
        content_parts.append("ET")
        stream = "\n".join(content_parts).encode("latin-1", "replace")
        objects[content_obj] = (f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1") + stream + b"\nendstream")
        objects[page_obj] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_obj} 0 R >>"
        ).encode("latin-1")

    objects[2] = (
        f"<< /Type /Pages /Kids [{' '.join(f'{r} 0 R' for r in page_refs)}] "
        f"/Count {len(page_refs)} >>"
    ).encode("latin-1")
    objects[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    max_obj = max(objects)
    output = io.BytesIO()
    output.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0] * (max_obj + 1)
    for obj_num in range(1, max_obj + 1):
        offsets[obj_num] = output.tell()
        output.write(f"{obj_num} 0 obj\n".encode("ascii"))
        output.write(objects[obj_num])
        output.write(b"\nendobj\n")

    xref_pos = output.tell()
    output.write(f"xref\n0 {max_obj + 1}\n".encode("ascii"))
    output.write(b"0000000000 65535 f \n")
    for obj_num in range(1, max_obj + 1):
        output.write(f"{offsets[obj_num]:010d} 00000 n \n".encode("ascii"))
    output.write(
        f"trailer\n<< /Size {max_obj + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("ascii")
    )
    return output.getvalue()


@api_bp.route('/worker/export/<worker_id>', methods=['GET'])
def export_worker_report(worker_id):
    import io, csv
    from flask import send_file
    fmt=request.args.get('format','csv').lower()
    start=request.args.get('start_date'); end=request.args.get('end_date')
    try:
        start_date = _parse_iso_date(start, 'start date') if start else None
        end_date = _parse_iso_date(end, 'end date') if end else None
    except ValueError as exc:
        return jsonify({'status':'error','message':str(exc)}), 400
    if start_date and end_date and start_date > end_date:
        return jsonify({'status':'error','message':'Start date cannot be after end date.'}), 400
    conn=get_db()
    worker=conn.execute('SELECT * FROM workers WHERE worker_id=?',(worker_id,)).fetchone()
    if not worker:
        conn.close(); return jsonify({'status':'error','message':'Worker not found'}),404
    q='SELECT id, action, timestamp FROM logs WHERE worker_id=?'; params=[worker_id]
    if start_date:q+=' AND timestamp>=?';params.append(start_date.isoformat()+' 00:00:00')
    if end_date:q+=' AND timestamp<=?';params.append(end_date.isoformat()+' 23:59:59')
    q+=' ORDER BY timestamp ASC, id ASC'
    rows=[dict(r) for r in conn.execute(q,tuple(params)).fetchall()]; conn.close()
    filename=f"{re.sub(r'[^A-Za-z0-9_-]+','_',worker['name'] or worker_id)}_attendance"
    if fmt=='csv':
        buf=io.StringIO(); w=csv.writer(buf); w.writerow(['Worker','Worker ID','Date','Time','Action','Card UID'])
        for r in rows:w.writerow([worker['name'],worker_id,r['timestamp'][:10],r['timestamp'][11:],'IN' if r['action']=='IN' else 'OUT',''])
        return send_file(io.BytesIO(buf.getvalue().encode('utf-8-sig')),as_attachment=True,download_name=filename+'.csv',mimetype='text/csv')
    if fmt in {'xlsx','excel'}:
        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment
        wb=Workbook(); ws=wb.active; ws.title='Attendance'; ws.append(['Worker','Worker ID','Date','Time','Action'])
        for cell in ws[1]: cell.font=Font(bold=True); cell.alignment=Alignment(horizontal='center')
        for r in rows: ws.append([worker['name'],worker_id,r['timestamp'][:10],r['timestamp'][11:],r['action']])
        for col,width in zip('ABCDE',[28,16,14,10,10]):ws.column_dimensions[col].width=width
        out=io.BytesIO();wb.save(out);out.seek(0);return send_file(out,as_attachment=True,download_name=filename+'.xlsx',mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    if fmt=='pdf':
        pdf_bytes = _build_simple_attendance_pdf(worker['name'], worker_id, rows)
        return send_file(io.BytesIO(pdf_bytes), as_attachment=(request.args.get('inline') != '1'), download_name=filename+'.pdf', mimetype='application/pdf')
    return jsonify({'status':'error','message':'Unsupported export format.'}),400



@api_bp.route('/worker/pdf-preview/<worker_id>', methods=['GET'])
def worker_pdf_preview(worker_id):
    cfg = load_config()
    conn = get_db()
    worker = conn.execute('SELECT * FROM workers WHERE worker_id=?', (worker_id,)).fetchone()
    conn.close()
    if not worker:
        return jsonify({'status':'error','message':'Worker not found'}), 404
    return render_template('dashboard/pdf_preview.html', worker_id=worker_id, worker_name=worker['name'], cfg=cfg, start_date=request.args.get('start_date',''), end_date=request.args.get('end_date',''))

@api_bp.route('/worker/report/<worker_id>', methods=['GET'])
def worker_report_page(worker_id):
    cfg = load_config()
    return render_template('dashboard/report.html', worker_id=worker_id, cfg=cfg)