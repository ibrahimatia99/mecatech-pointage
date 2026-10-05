import io
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


class ProductionCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory()
        cls.data_dir = Path(cls.tempdir.name) / "data"
        cls.data_dir.mkdir(parents=True, exist_ok=True)
        import db
        cls.db = db
        cls.original_get_app_data_dir = db.get_app_data_dir
        db.get_app_data_dir = lambda: cls.tempdir.name
        cfg = db.load_config()
        cfg.update({
            "db_path": str(cls.data_dir),
            "app_password": "admin",
            "auto_checkout_enabled": True,
            "auto_checkout_trigger_time": "20:00",
            "auto_checkout_time": "18:00",
            "work_start_time": "08:00",
            "late_after_time": "08:10",
            "work_end_time": "17:00",
            "expected_daily_hours": 8,
        })
        db.save_config(cfg)
        db.init_db()

    @classmethod
    def tearDownClass(cls):
        cls.db.get_app_data_dir = cls.original_get_app_data_dir
        cls.tempdir.cleanup()

    def setUp(self):
        conn = self.db.get_db()
        conn.execute("DELETE FROM leaves")
        conn.execute("DELETE FROM audit_log")
        conn.execute("DELETE FROM logs")
        conn.execute("DELETE FROM workers")
        conn.commit()
        conn.close()

    def _add_worker_with_open_in(self):
        conn = self.db.get_db()
        conn.execute(
            "INSERT INTO workers(worker_id,name,cin,phone,card_uid) VALUES(?,?,?,?,?)",
            ("W1", "Test Worker", "12345678", "21690000000", "ABCDEF"),
        )
        conn.execute(
            "INSERT INTO logs(worker_id,card_uid,action,timestamp) VALUES(?,?,?,?)",
            ("W1", "ABCDEF", "IN", "2026-10-03 08:05:00"),
        )
        # Add a deterministic current-day punch before the late threshold
        # so the dashboard status is independent of the runner clock.
        conn.execute(
            "INSERT INTO logs(worker_id,card_uid,action,timestamp) VALUES(?,?,?,?)",
            ("W1", "ABCDEF", "IN", f"{datetime.now().strftime("%Y-%m-%d")} 08:05:00"),
        )
        conn.commit()
        conn.close()

    def test_required_files_and_contract_assets(self):
        root = Path(__file__).resolve().parents[1]
        required = [
            "app.py", "db.py", "routes/api.py", "routes/settings.py",
            "templates/dashboard/index.html", "templates/dashboard/report.html",
            "MecatechPointage.spec", "installer.iss", ".github/workflows/build-windows.yml",
        ]
        for rel in required:
            self.assertTrue((root / rel).exists(), rel)

    def test_schema_and_auto_checkout_idempotency(self):
        conn = self.db.get_db()
        conn.execute("INSERT INTO workers(worker_id,name,cin,phone,card_uid) VALUES(?,?,?,?,?)", ("W1", "Test Worker", "12345678", "21690000000", "ABCDEF"))
        conn.execute("INSERT INTO logs(worker_id,card_uid,action,timestamp) VALUES(?,?,?,?)", ("W1", "ABCDEF", "IN", "2026-10-03 08:05:00"))
        conn.commit(); conn.close()
        from routes.api import process_auto_checkouts
        self.assertEqual(process_auto_checkouts(datetime(2026, 10, 4, 21, 0, 0)), 1)
        self.assertEqual(process_auto_checkouts(datetime(2026, 10, 4, 21, 0, 0)), 0)
        conn = self.db.get_db()
        out_rows = conn.execute(
            "SELECT action,timestamp,card_uid FROM logs WHERE worker_id='W1' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        schema = conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0]
        conn.close()
        self.assertEqual(schema, "4")
        self.assertEqual(out_rows["action"], "OUT")
        self.assertEqual(out_rows["timestamp"], "2026-10-03 18:00:00")
        self.assertEqual(out_rows["card_uid"], "AUTO_CHECKOUT")

    def test_dashboard_leave_edit_delete_and_exports(self):
        self._add_worker_with_open_in()
        from flask import Flask
        from routes.api import api_bp
        from routes.settings import settings_bp

        test_app = Flask(__name__)
        test_app.secret_key = "test"
        test_app.config["UPLOAD_FOLDER"] = str(self.data_dir / "uploads")
        os.makedirs(test_app.config["UPLOAD_FOLDER"], exist_ok=True)
        test_app.register_blueprint(api_bp, url_prefix="/api")
        test_app.register_blueprint(settings_bp, url_prefix="/api/settings")
        client = test_app.test_client()

        r = client.get("/api/dashboard")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["workers"][0]["status"], "PRESENT")

        r = client.post(
            "/api/leave/add",
            json={
                "worker_id": "W1", "leave_type": "Vacation",
                "start_date": "2026-10-05", "end_date": "2026-10-06", "note": "Test",
            },
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(client.get("/api/leave/list").get_json()["leaves"]), 1)

        r = client.get("/api/worker/history/W1?start_date=2026-10-01&end_date=2026-10-31")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        future = [d for d in data["calendar_days"] if d["iso_date"] > datetime.now().date().isoformat()]
        self.assertTrue(future)
        self.assertTrue(all(d["status"] == "UPCOMING" for d in future))

        conn = self.db.get_db()
        log_id = conn.execute("SELECT id FROM logs ORDER BY id LIMIT 1").fetchone()[0]
        conn.close()
        r = client.put(
            f"/api/worker/log/{log_id}",
            json={"timestamp": "2026-10-03 08:10", "action": "OUT", "reason": "Correction"},
        )
        self.assertEqual(r.status_code, 200)
        r = client.delete(f"/api/worker/log/{log_id}")
        self.assertEqual(r.status_code, 200)

        audit = client.get("/api/audit").get_json()["audit"]
        self.assertTrue(any(a["action"] == "attendance_edited" for a in audit))
        self.assertTrue(any(a["action"] == "attendance_deleted" for a in audit))

        for fmt in ("csv", "xlsx", "pdf"):
            r = client.get(f"/api/worker/export/W1?format={fmt}")
            self.assertEqual(r.status_code, 200, r.data[:200])
            self.assertTrue(r.data)
        self.assertTrue(client.post("/api/settings/backup").is_json)


class AdditionalProductionInvariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory()
        cls.data_dir = Path(cls.tempdir.name) / "data"
        cls.data_dir.mkdir(parents=True, exist_ok=True)
        import db
        cls.db = db
        cls.original_get_app_data_dir = db.get_app_data_dir
        db.get_app_data_dir = lambda: cls.tempdir.name
        cfg = db.load_config()
        cfg.update({"db_path": str(cls.data_dir), "auto_checkout_enabled": False})
        db.save_config(cfg)
        db._DISCOVERY_DONE = True
        db.init_db()

    @classmethod
    def tearDownClass(cls):
        cls.db.get_app_data_dir = cls.original_get_app_data_dir
        cls.tempdir.cleanup()

    def setUp(self):
        conn = self.db.get_db()
        for table in ("leaves", "audit_log", "logs", "joker_assignments", "joker_cards", "workers"):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
        conn.close()

    def test_delete_worker_cleans_leave_records(self):
        conn = self.db.get_db()
        conn.execute("INSERT INTO workers(worker_id,name) VALUES(?,?)", ("W1", "Worker"))
        conn.execute("INSERT INTO leaves(worker_id,leave_type,start_date,end_date,note) VALUES(?,?,?,?,?)", ("W1", "Vacation", "2026-10-05", "2026-10-06", "x"))
        conn.commit(); conn.close()
        from flask import Flask
        from routes.api import api_bp
        app = Flask(__name__); app.secret_key = "test"; app.register_blueprint(api_bp, url_prefix="/api")
        r = app.test_client().delete("/api/worker/delete/W1")
        self.assertEqual(r.status_code, 200)
        conn = self.db.get_db()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM leaves WHERE worker_id='W1'").fetchone()[0], 0)
        self.assertTrue(conn.execute("SELECT 1 FROM audit_log WHERE action='worker_deleted'").fetchone())
        conn.close()

    def test_edit_timestamp_never_changes_action_or_blocks_sequence(self):
        conn = self.db.get_db()
        conn.execute("INSERT INTO workers(worker_id,name) VALUES(?,?)", ("W1", "Worker"))
        rows = [
            ("W1", "IN", "2026-10-03 08:00:00"),
            ("W1", "OUT", "2026-10-03 17:00:00"),
            ("W1", "IN", "2026-10-04 08:00:00"),
        ]
        for w,a,t in rows:
            conn.execute("INSERT INTO logs(worker_id,action,timestamp) VALUES(?,?,?)", (w,a,t))
        conn.commit()
        log_id = conn.execute("SELECT id FROM logs WHERE timestamp='2026-10-03 17:00:00'").fetchone()[0]
        conn.close()
        from flask import Flask
        from routes.api import api_bp
        app = Flask(__name__); app.secret_key = "test"; app.register_blueprint(api_bp, url_prefix="/api")
        r = app.test_client().put(f"/api/worker/log/{log_id}", json={"timestamp":"2026-10-03 16:00", "action":"IN"})
        self.assertEqual(r.status_code, 200)
        conn = self.db.get_db()
        row = conn.execute("SELECT action,timestamp FROM logs WHERE id=?", (log_id,)).fetchone()
        conn.close()
        self.assertEqual(row['action'], 'OUT')
        self.assertEqual(row['timestamp'], '2026-10-03 16:00:00')

    def test_settings_time_rules_reject_impossible_schedule(self):
        from flask import Flask
        from routes.settings import settings_bp
        app = Flask(__name__); app.secret_key = "test"; app.register_blueprint(settings_bp, url_prefix="/api/settings")
        r = app.test_client().post("/api/settings/update", json={
            "work_start_time":"09:00", "late_after_time":"08:10", "work_end_time":"17:00",
            "expected_daily_hours":"8", "auto_checkout_enabled":"false",
            "auto_checkout_trigger_time":"20:00", "auto_checkout_time":"18:00",
            "app_name":"Test", "language":"en", "primary_color":"#ff5a00", "purge_days":"0"
        })
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
