from flask import Blueprint, request, jsonify, render_template
from datetime import datetime, timedelta
from db import get_db, load_config, save_config, purge_old_logs

api_bp = Blueprint('api', __name__)

LAST_ESP32_HEARTBEAT = None

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
    purge_old_logs()
    return jsonify({"status": "ok"}), 200

# --- WORKER CARD ENROLLMENT ROUTES ---
@api_bp.route('/enroll/start', methods=['POST'])
def start_enroll():
    global ENROLL_STATE, ENROLL_WORKER_ID, ENROLL_WORKER_NAME, ENROLL_SCANNED_UID
    data = request.json or {}
    worker_id = data.get('worker_id')
    
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
    JOKER_ENROLL_LABEL = (data.get('label') or 'Joker Card').strip()
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
    global LAST_ESP32_HEARTBEAT, ENROLL_STATE, ENROLL_WORKER_ID, ENROLL_WORKER_NAME, ENROLL_SCANNED_UID
    global JOKER_ENROLL_STATE, JOKER_ENROLL_LABEL, JOKER_SCANNED_UID, JOKER_ENROLL_ERROR
    global SPARE_PENDING, SPARE_CARD_UID
    
    LAST_ESP32_HEARTBEAT = datetime.now()
    data = request.json or {}
    uid = data.get('card_uid')

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

# --- DASHBOARD & WORKER MANAGEMENT ---
@api_bp.route('/dashboard', methods=['GET'])
def get_dashboard():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM workers")
    workers = [dict(row) for row in c.fetchall()]
    
    for w in workers:
        c.execute("SELECT action, timestamp FROM logs WHERE worker_id = ? ORDER BY timestamp DESC LIMIT 1", (w['worker_id'],))
        last_log = c.fetchone()
        w['status'] = last_log['action'] if last_log else "OUT"
        w['last_time'] = last_log['timestamp'] if last_log else "No activity"
    conn.close()
    
    online = bool(LAST_ESP32_HEARTBEAT and (datetime.now() - LAST_ESP32_HEARTBEAT).total_seconds() < 10)
    return jsonify({"workers": workers, "esp32_online": online})

@api_bp.route('/worker/add', methods=['POST'])
def add_worker():
    data = request.json or {}
    card_uid = data.get('card_uid') or None

    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("""
            INSERT INTO workers (worker_id, name, cin, phone, card_uid) 
            VALUES (?, ?, ?, ?, ?)
        """, (
            data['worker_id'], 
            data['name'], 
            data.get('cin', ''), 
            data.get('phone', ''), 
            card_uid
        ))
        conn.commit()
        conn.close()
        return jsonify({"status": "success"}), 200
    except Exception as e:
        conn.close()
        return jsonify({"status": "error", "message": str(e)}), 400

@api_bp.route('/worker/update', methods=['PUT'])
def update_worker():
    data = request.json or {}
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("""
            UPDATE workers 
            SET name = ?, cin = ?, phone = ? 
            WHERE worker_id = ?
        """, (
            data['name'], 
            data.get('cin', ''), 
            data.get('phone', ''), 
            data['worker_id']
        ))
        conn.commit()
        conn.close()
        return jsonify({"status": "success"}), 200
    except Exception as e:
        conn.close()
        return jsonify({"status": "error", "message": str(e)}), 400

@api_bp.route('/worker/delete/<worker_id>', methods=['DELETE'])
def delete_worker(worker_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM workers WHERE worker_id = ?", (worker_id,))
    c.execute("DELETE FROM logs WHERE worker_id = ?", (worker_id,))
    c.execute("DELETE FROM joker_assignments WHERE worker_id = ?", (worker_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "deleted"}), 200

# --- ATTENDANCE REPORTING ENGINE ---
@api_bp.route('/worker/history/<worker_id>', methods=['GET'])
def get_history(worker_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM workers WHERE worker_id = ?", (worker_id,))
    worker = c.fetchone()

    start_param = request.args.get('start_date')
    end_param = request.args.get('end_date')

    query = "SELECT action, timestamp FROM logs WHERE worker_id = ?"
    params = [worker_id]

    if start_param:
        query += " AND timestamp >= ?"
        params.append(f"{start_param} 00:00:00")
    if end_param:
        query += " AND timestamp <= ?"
        params.append(f"{end_param} 23:59:59")

    query += " ORDER BY timestamp ASC"

    c.execute(query, tuple(params))
    logs = [dict(row) for row in c.fetchall()]
    conn.close()

    days_data = {}
    total_filtered_seconds = 0

    now = datetime.now()
    start_of_week = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    total_week_seconds = 0
    total_month_seconds = 0

    for i in range(len(logs)):
        entry = logs[i]
        ts = datetime.strptime(entry['timestamp'], "%Y-%m-%d %H:%M:%S")
        day_str = ts.strftime("%A, %b %d, %Y")

        if day_str not in days_data:
            days_data[day_str] = {"logs": [], "seconds": 0}

        days_data[day_str]["logs"].append(entry)

        if entry['action'] == 'IN' and i + 1 < len(logs):
            next_entry = logs[i + 1]
            if next_entry['action'] == 'OUT':
                next_ts = datetime.strptime(next_entry['timestamp'], "%Y-%m-%d %H:%M:%S")
                duration = (next_ts - ts).total_seconds()
                if duration > 0:
                    days_data[day_str]["seconds"] += duration
                    total_filtered_seconds += duration
                    if ts >= start_of_week:
                        total_week_seconds += duration
                    if ts >= start_of_month:
                        total_month_seconds += duration

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

    return jsonify({
        "worker": dict(worker) if worker else {},
        "days": formatted_days,
        "week_total": format_total(total_week_seconds),
        "month_total": format_total(total_month_seconds),
        "range_total": format_total(total_filtered_seconds)
    })

@api_bp.route('/worker/report/<worker_id>', methods=['GET'])
def worker_report_page(worker_id):
    cfg = load_config()
    return render_template('dashboard/report.html', worker_id=worker_id, cfg=cfg)