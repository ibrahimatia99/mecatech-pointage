import random
from datetime import datetime, timedelta
from db import get_db

def seed_demo_data():
    conn = get_db()
    c = conn.cursor()

    # 1. Clear existing workers & logs
    c.execute("DELETE FROM logs;")
    c.execute("DELETE FROM workers;")
    c.execute("DELETE FROM sqlite_sequence WHERE name IN ('logs', 'workers');")

    # 2. Define 4 sample workers
    sample_workers = [
        {"worker_id": "W1001", "name": "Sami Ben Ali", "cin": "08123456", "phone": "21620111222", "card_uid": "A1B2C3D4"},
        {"worker_id": "W1002", "name": "Mohamed Trabelsi", "cin": "09456789", "phone": "21620333444", "card_uid": "E5F6G7H8"},
        {"worker_id": "W1003", "name": "Youssef Gharbi", "cin": "07890123", "phone": "21620555666", "card_uid": "I9J0K1L2"},
        {"worker_id": "W1004", "name": "Amine Mansour", "cin": "05123987", "phone": "21620777888", "card_uid": "M3N4O5P6"},
    ]

    for w in sample_workers:
        c.execute("""
            INSERT INTO workers (worker_id, name, cin, phone, card_uid) 
            VALUES (?, ?, ?, ?, ?)
        """, (w["worker_id"], w["name"], w["cin"], w["phone"], w["card_uid"]))

    # 3. Generate attendance records for the last 40 days
    today = datetime.now()
    start_date = today - timedelta(days=40)

    log_entries = []

    for day_offset in range(41):
        current_day = start_date + timedelta(days=day_offset)
        
        # Skip Weekends (Saturday = 5, Sunday = 6)
        if current_day.weekday() in (5, 6):
            continue

        for w in sample_workers:
            # 5% chance of absence
            if random.random() < 0.05:
                continue

            # Natural time variation around 8:00 to 12:00 and 13:00 to 17:00
            morning_in_jitter = random.randint(-5, 10)
            morning_out_jitter = random.randint(-2, 5)
            afternoon_in_jitter = random.randint(-2, 5)
            evening_out_jitter = random.randint(-5, 12)

            morning_in = current_day.replace(hour=8, minute=0, second=0) + timedelta(minutes=morning_in_jitter)
            lunch_out = current_day.replace(hour=12, minute=0, second=0) + timedelta(minutes=morning_out_jitter)
            lunch_in = current_day.replace(hour=13, minute=0, second=0) + timedelta(minutes=afternoon_in_jitter)
            evening_out = current_day.replace(hour=17, minute=0, second=0) + timedelta(minutes=evening_out_jitter)

            log_entries.append((w["worker_id"], w["card_uid"], "IN", morning_in.strftime("%Y-%m-%d %H:%M:%S")))
            log_entries.append((w["worker_id"], w["card_uid"], "OUT", lunch_out.strftime("%Y-%m-%d %H:%M:%S")))
            log_entries.append((w["worker_id"], w["card_uid"], "IN", lunch_in.strftime("%Y-%m-%d %H:%M:%S")))
            log_entries.append((w["worker_id"], w["card_uid"], "OUT", evening_out.strftime("%Y-%m-%d %H:%M:%S")))

    log_entries.sort(key=lambda x: x[3])
    for entry in log_entries:
        c.execute("""
            INSERT INTO logs (worker_id, card_uid, action, timestamp) 
            VALUES (?, ?, ?, ?)
        """, entry)

    conn.commit()
    conn.close()
    print("Demo database populated successfully with 4 workers and 40 days of history!")
if __name__ == "__main__":
    seed_demo_data()
