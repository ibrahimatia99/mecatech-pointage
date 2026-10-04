import os
import tempfile
import unittest
from pathlib import Path


class SettingsSaveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        import db
        cls.db = db
        cls.original_get_app_data_dir = db.get_app_data_dir
        db.get_app_data_dir = lambda: cls.tmp.name
        db._DISCOVERY_DONE = True
        cfg = db.load_config()
        cfg['db_path'] = os.path.join(cls.tmp.name, 'data')
        db.save_config(cfg)
        db.init_db()

    @classmethod
    def tearDownClass(cls):
        cls.db.get_app_data_dir = cls.original_get_app_data_dir
        cls.tmp.cleanup()

    def test_json_settings_save_persists_without_database_path_work(self):
        from flask import Flask
        from routes.settings import settings_bp
        app = Flask(__name__)
        app.secret_key = 'test'
        app.config['UPLOAD_FOLDER'] = os.path.join(self.tmp.name, 'data', 'uploads')
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        app.register_blueprint(settings_bp, url_prefix='/api/settings')
        client = app.test_client()
        response = client.post('/api/settings/update', json={
            'app_name': 'Production Test',
            'language': 'fr',
            'primary_color': '#123456',
            'purge_days': '0',
            'work_start_time': '08:00',
            'late_after_time': '08:10',
            'work_end_time': '17:00',
            'expected_daily_hours': '8',
            'auto_checkout_enabled': 'true',
            'auto_checkout_trigger_time': '20:00',
            'auto_checkout_time': '18:00',
        })
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body['status'], 'success')
        cfg = self.db.load_config()
        self.assertEqual(cfg['app_name'], 'Production Test')
        self.assertEqual(cfg.get('theme', 'light'), 'light')
        self.assertEqual(cfg['language'], 'fr')
        self.assertTrue(cfg['auto_checkout_enabled'])

    def test_form_settings_save_path_returns_json_and_persists(self):
        from flask import Flask
        from routes.settings import settings_bp
        app = Flask(__name__)
        app.secret_key = 'test'
        app.config['UPLOAD_FOLDER'] = os.path.join(self.tmp.name, 'data', 'uploads')
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        app.register_blueprint(settings_bp, url_prefix='/api/settings')
        response = app.test_client().post('/api/settings/update', data={
            '_response':'json', 'app_name':'Form Save Test', 'language':'en',
            'primary_color':'#445566', 'purge_days':'0', 'work_start_time':'08:00',
            'late_after_time':'08:15', 'work_end_time':'17:00', 'expected_daily_hours':'8',
            'auto_checkout_trigger_time':'20:00', 'auto_checkout_time':'18:00',
        }, headers={'Accept':'application/json'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['status'], 'success')
        self.assertEqual(self.db.load_config()['app_name'], 'Form Save Test')
        self.assertEqual(self.db.load_config()['primary_color'], '#445566')

    def test_fast_form_settings_save(self):
        from flask import Flask
        from routes.settings import settings_bp
        app = Flask(__name__)
        app.secret_key = 'test'
        app.register_blueprint(settings_bp, url_prefix='/api/settings')
        response = app.test_client().post('/api/settings/update-fast', data={
            'app_name':'Fast Settings Test','language':'fr','primary_color':'#abcdef',
            'purge_days':'0','work_start_time':'08:00','late_after_time':'08:10','work_end_time':'17:00',
            'expected_daily_hours':'8','auto_checkout_enabled':'on','auto_checkout_trigger_time':'20:00','auto_checkout_time':'18:00',
            'db_path': os.path.join(self.tmp.name, 'data'),
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['status'], 'success')
        saved = self.db.load_config()
        self.assertEqual(saved['app_name'], 'Fast Settings Test')
        self.assertEqual(saved['language'], 'fr')

    def test_bad_color_is_rejected(self):
        from flask import Flask
        from routes.settings import settings_bp
        app = Flask(__name__)
        app.secret_key = 'test'
        app.register_blueprint(settings_bp, url_prefix='/api/settings')
        response = app.test_client().post('/api/settings/update', json={'primary_color':'orange'})
        self.assertEqual(response.status_code, 400)


if __name__ == '__main__':
    unittest.main(verbosity=2)
