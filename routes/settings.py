import logging
import os
import platform
import re
import threading
from datetime import datetime
import shutil
from flask import Blueprint, request, jsonify, current_app, url_for, redirect
from werkzeug.utils import secure_filename
from db import load_config, save_config, backup_database, list_backups, restore_database, write_audit

settings_bp = Blueprint('settings', __name__)

@settings_bp.route('/choose-directory', methods=['POST'])
def choose_directory():
    try:
        selected_dir = ""

        # Use pywebview native file dialog window dialog if running inside desktop app
        try:
            import webview
            # active_window() targets the current pywebview desktop container securely
            window = webview.active_window()
            if window:
                result = window.create_file_dialog(
                    webview.FOLDER_DIALOG, 
                    title="Select Database Storage Directory"
                )
                if result and isinstance(result, tuple) and len(result) > 0:
                    selected_dir = result[0]
                elif result and isinstance(result, str):
                    selected_dir = result
        except Exception:
            pass

        # Fallback for standard browser testing or if webview context is missing
        if not selected_dir:
            if platform.system() == "Windows":
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                root.attributes('-topmost', True)
                selected_dir = filedialog.askdirectory(title='Select Database Storage Directory')
                root.destroy()
            elif platform.system() == "Darwin":
                import subprocess
                cmd = 'osascript -e "POSIX path of (choose folder with prompt \\"Select Database Storage Directory\\")"'
                process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                stdout, _ = process.communicate()
                selected_dir = stdout.decode('utf-8').strip()

        if selected_dir and os.path.exists(selected_dir):
            return jsonify({"status": "success", "path": selected_dir}), 200
            
        return jsonify({"status": "cancelled"}), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@settings_bp.route('/update-fast', methods=['POST'])
def update_settings_fast():
    """Fast JSON settings persistence path used by the desktop WebView.

    This route deliberately touches only config.json. It does not open SQLite,
    parse multipart uploads, or wait for audit/maintenance work.
    """
    try:
        cfg = load_config()
        form = request.form

        def get(name, default=None):
            value = form.get(name)
            return default if value is None else value

        previous_db_path = cfg.get('db_path')
        selected_db_path = get('db_path', previous_db_path)
        if selected_db_path:
            selected_db_path = os.path.abspath(os.path.expanduser(str(selected_db_path)))
            os.makedirs(selected_db_path, exist_ok=True)
        cfg['db_path'] = selected_db_path
        cfg['app_name'] = str(get('app_name', cfg.get('app_name')) or 'Mecatech Pointage').strip()[:120]

        password = str(get('app_password', '') or '').strip()
        if password:
            from werkzeug.security import generate_password_hash
            cfg['app_password'] = generate_password_hash(password)
        cfg['theme'] = 'light'

        language = str(get('language', cfg.get('language', 'en')) or 'en').lower()
        if language not in {'en', 'fr', 'ar'}:
            return jsonify({'status': 'error', 'message': 'Invalid language selection.'}), 400
        cfg['language'] = language

        primary_color = str(get('primary_color', cfg.get('primary_color', '#ff5a00')) or '#ff5a00').strip()
        if not re.fullmatch(r'#[0-9A-Fa-f]{6}', primary_color):
            return jsonify({'status': 'error', 'message': 'Primary color must be a valid 6-digit hexadecimal color.'}), 400
        cfg['primary_color'] = primary_color

        try:
            cfg['work_start_time'] = datetime.strptime(str(get('work_start_time', cfg.get('work_start_time', '08:00')) or '08:00'), '%H:%M').strftime('%H:%M')
            cfg['late_after_time'] = datetime.strptime(str(get('late_after_time', cfg.get('late_after_time', '08:10')) or '08:10'), '%H:%M').strftime('%H:%M')
            cfg['work_end_time'] = datetime.strptime(str(get('work_end_time', cfg.get('work_end_time', '17:00')) or '17:00'), '%H:%M').strftime('%H:%M')
            start_obj = datetime.strptime(cfg['work_start_time'], '%H:%M')
            late_obj = datetime.strptime(cfg['late_after_time'], '%H:%M')
            end_obj = datetime.strptime(cfg['work_end_time'], '%H:%M')
            if not (start_obj <= late_obj <= end_obj):
                return jsonify({'status':'error','message':'Attendance times must follow Work Start ≤ Late After ≤ Work End.'}), 400
            cfg['expected_daily_hours'] = max(1, min(24, int(get('expected_daily_hours', cfg.get('expected_daily_hours', 8)))))
            if cfg['expected_daily_hours'] > (end_obj - start_obj).total_seconds() / 3600.0:
                return jsonify({'status':'error','message':'Expected daily hours cannot exceed the configured work interval.'}), 400
            cfg['purge_days'] = max(0, min(3650, int(get('purge_days', cfg.get('purge_days', 0)) or 0)))
            cfg['auto_checkout_enabled'] = str(get('auto_checkout_enabled', 'false')).strip().lower() in {'on','true','1','yes'}
            cfg['auto_checkout_trigger_time'] = datetime.strptime(str(get('auto_checkout_trigger_time', cfg.get('auto_checkout_trigger_time', '20:00')) or '20:00'), '%H:%M').strftime('%H:%M')
            cfg['auto_checkout_time'] = datetime.strptime(str(get('auto_checkout_time', cfg.get('auto_checkout_time', '18:00')) or '18:00'), '%H:%M').strftime('%H:%M')
            if datetime.strptime(cfg['auto_checkout_time'], '%H:%M') > datetime.strptime(cfg['auto_checkout_trigger_time'], '%H:%M'):
                return jsonify({'status':'error','message':'Checkout time must be earlier than or equal to the trigger time.'}), 400
        except (ValueError, TypeError):
            return jsonify({'status':'error','message':'Invalid attendance or auto-checkout settings.'}), 400

        # Persist configuration only. No SQLite operation is part of the response path.
        save_config(cfg)

        # Migrate existing branding files after the config write without delaying the HTTP response.
        if previous_db_path and selected_db_path and os.path.abspath(os.path.expanduser(str(previous_db_path))) != os.path.abspath(selected_db_path):
            old_upload_dir = os.path.join(os.path.abspath(os.path.expanduser(str(previous_db_path))), 'uploads')
            new_upload_dir = os.path.join(selected_db_path, 'uploads')
            if os.path.isdir(old_upload_dir):
                os.makedirs(new_upload_dir, exist_ok=True)
                for name in os.listdir(old_upload_dir):
                    src = os.path.join(old_upload_dir, name); dst = os.path.join(new_upload_dir, name)
                    if os.path.isfile(src) and not os.path.exists(dst):
                        try: shutil.copy2(src, dst)
                        except OSError: pass

        return jsonify({'status':'success','message':'Settings saved successfully.','settings':cfg}), 200
    except Exception as exc:
        logging.getLogger('mecatech').exception('Fast settings update failed')
        return jsonify({'status':'error','message':'Unable to save settings: ' + str(exc)}), 500


@settings_bp.route('/update', methods=['POST'])
def update_settings():
    """Persist settings quickly and atomically at the application layer.

    Normal settings changes must never wait on the attendance database. Database
    audit logging is deliberately moved to a short-lived background task after the
    configuration file has been committed, so a SQLite lock cannot make the Save
    button appear to hang.
    """
    try:
        cfg = load_config()
        accepts_json = 'application/json' in (request.headers.get('Accept') or '')
        is_json = bool(request.is_json or request.form.get('_response') == 'json' or accepts_json)
        payload = (request.get_json(silent=True) or {}) if request.is_json else request.form

        def value(name, default=None):
            incoming = payload.get(name) if payload is not None else None
            return default if incoming is None else incoming

        previous_db_path = cfg.get('db_path')
        selected_db_path = value('db_path', previous_db_path)
        if selected_db_path:
            selected_db_path = os.path.abspath(os.path.expanduser(str(selected_db_path)))
            os.makedirs(selected_db_path, exist_ok=True)
        cfg['db_path'] = selected_db_path
        cfg['app_name'] = str(value('app_name', cfg.get('app_name')) or 'Mecatech Pointage').strip()[:120]

        password = str(value('app_password', '') or '').strip()
        if password:
            from werkzeug.security import generate_password_hash
            cfg['app_password'] = generate_password_hash(password)
        cfg['theme'] = 'light'

        language = str(value('language', cfg.get('language', 'en')) or 'en').lower()
        if language not in {'en', 'fr', 'ar'}:
            return jsonify({'status': 'error', 'message': 'Invalid language selection.'}), 400
        cfg['language'] = language

        primary_color = str(value('primary_color', cfg.get('primary_color', '#ff5a00')) or '#ff5a00').strip()
        if not re.fullmatch(r'#[0-9A-Fa-f]{6}', primary_color):
            return jsonify({'status': 'error', 'message': 'Primary color must be a valid 6-digit hexadecimal color.'}), 400
        cfg['primary_color'] = primary_color

        def valid_hhmm(name, default):
            raw = str(value(name, cfg.get(name, default)) or default)
            datetime.strptime(raw, '%H:%M')
            return raw

        try:
            cfg['work_start_time'] = valid_hhmm('work_start_time', '08:00')
            cfg['late_after_time'] = valid_hhmm('late_after_time', '08:10')
            cfg['work_end_time'] = valid_hhmm('work_end_time', '17:00')
            start_obj = datetime.strptime(cfg['work_start_time'], '%H:%M')
            late_obj = datetime.strptime(cfg['late_after_time'], '%H:%M')
            end_obj = datetime.strptime(cfg['work_end_time'], '%H:%M')
            if not (start_obj <= late_obj <= end_obj):
                return jsonify({'status': 'error', 'message': 'Attendance times must follow Work Start ≤ Late After ≤ Work End.'}), 400
            cfg['expected_daily_hours'] = max(1, min(24, int(value('expected_daily_hours', cfg.get('expected_daily_hours', 8)))))
            span_hours = (end_obj - start_obj).total_seconds() / 3600.0
            if cfg['expected_daily_hours'] > span_hours:
                return jsonify({'status': 'error', 'message': 'Expected daily hours cannot exceed the configured work interval.'}), 400
            purge = int(value('purge_days', cfg.get('purge_days', 0)) or 0)
            cfg['purge_days'] = max(0, min(3650, purge))
            cfg['auto_checkout_enabled'] = str(value('auto_checkout_enabled', '')).strip().lower() in {'on', 'true', '1', 'yes'}
            trigger_time = valid_hhmm('auto_checkout_trigger_time', '20:00')
            checkout_time = valid_hhmm('auto_checkout_time', '18:00')
            trigger_obj = datetime.strptime(trigger_time, '%H:%M')
            checkout_obj = datetime.strptime(checkout_time, '%H:%M')
            if checkout_obj > trigger_obj:
                return jsonify({'status': 'error', 'message': 'Checkout time must be earlier than or equal to the trigger time.'}), 400
            cfg['auto_checkout_trigger_time'] = trigger_time
            cfg['auto_checkout_time'] = checkout_time
        except (ValueError, TypeError):
            return jsonify({'status': 'error', 'message': 'Invalid attendance or auto-checkout settings.'}), 400

        # Image uploads use the same endpoint only when the browser actually
        # supplied a file. Normal saves remain tiny JSON requests.
        upload_dir = os.path.join(cfg['db_path'], 'uploads')
        os.makedirs(upload_dir, exist_ok=True)
        current_app.config['UPLOAD_FOLDER'] = upload_dir
        if not is_json:
            if 'app_logo' in request.files:
                file = request.files['app_logo']
                if file and file.filename:
                    filename = 'logo_' + secure_filename(file.filename)
                    file.save(os.path.join(upload_dir, filename))
                    cfg['app_logo'] = url_for('serve_uploads', filename=filename)
            if 'app_icon' in request.files:
                file = request.files['app_icon']
                if file and file.filename:
                    filename = 'icon_' + secure_filename(file.filename)
                    file.save(os.path.join(upload_dir, filename))
                    cfg['app_icon'] = url_for('serve_uploads', filename=filename)

        # Keep uploaded branding available if the database/data directory was moved.
        if previous_db_path and selected_db_path and os.path.abspath(os.path.expanduser(str(previous_db_path))) != os.path.abspath(selected_db_path):
            old_upload_dir = os.path.join(os.path.abspath(os.path.expanduser(str(previous_db_path))), 'uploads')
            new_upload_dir = os.path.join(selected_db_path, 'uploads')
            if os.path.isdir(old_upload_dir):
                os.makedirs(new_upload_dir, exist_ok=True)
                for name in os.listdir(old_upload_dir):
                    src = os.path.join(old_upload_dir, name)
                    dst = os.path.join(new_upload_dir, name)
                    if os.path.isfile(src) and not os.path.exists(dst):
                        try:
                            shutil.copy2(src, dst)
                        except OSError:
                            logging.getLogger('mecatech').warning('Could not migrate upload asset: %s', src)

        save_config(cfg)

        # Do not block this HTTP request on SQLite. Auditing is still retained and
        # uses the post-save configuration in its own database connection.
        summary = 'Application settings changed.'
        def audit_settings_change():
            try:
                write_audit('settings_updated', 'settings', 'global', summary)
            except Exception:
                logging.getLogger('mecatech').exception('Settings saved but audit entry failed')
        threading.Thread(target=audit_settings_change, name='Mecatech-Settings-Audit', daemon=True).start()

        response_data = {'status': 'success', 'message': 'Settings saved successfully.', 'settings': cfg}
        # A native form POST (e.g. JS disabled) gets a normal redirect rather than
        # being left on a raw JSON response. AJAX/JSON clients always get JSON.
        if not is_json:
            return redirect(url_for('index', settings_saved='1'))
        return jsonify(response_data), 200
    except Exception as exc:
        current_app.logger.exception('Settings update failed')
        return jsonify({'status': 'error', 'message': 'Unable to save settings: ' + str(exc)}), 500

@settings_bp.route('/upload-assets', methods=['POST'])
def upload_assets():
    """Upload branding assets independently from the settings save transaction."""
    try:
        cfg = load_config()
        upload_dir = os.path.join(os.path.abspath(os.path.expanduser(cfg.get('db_path') or os.getcwd())), 'uploads')
        os.makedirs(upload_dir, exist_ok=True)
        saved = {}
        for field, prefix, config_key in (('app_logo', 'logo_', 'app_logo'), ('app_icon', 'icon_', 'app_icon')):
            file = request.files.get(field)
            if not file or not file.filename:
                continue
            filename = prefix + secure_filename(file.filename)
            if not filename or filename == prefix:
                return jsonify({'status': 'error', 'message': f'Invalid {field} filename.'}), 400
            destination = os.path.join(upload_dir, filename)
            file.save(destination)
            cfg[config_key] = url_for('serve_uploads', filename=filename)
            saved[config_key] = cfg[config_key]
        if saved:
            save_config(cfg)
        return jsonify({'status': 'success', 'assets': saved}), 200
    except Exception as exc:
        current_app.logger.exception('Asset upload failed')
        return jsonify({'status': 'error', 'message': 'Unable to save image assets: ' + str(exc)}), 500


@settings_bp.route('/backup', methods=['POST'])
def create_backup():
    try:
        path = backup_database()
        write_audit('backup_created', 'database', None, os.path.basename(path) if path else 'none')
        return jsonify({'status':'success','message':'Backup created.','file':os.path.basename(path) if path else None,'backups':list_backups()}), 200
    except Exception as exc:
        return jsonify({'status':'error','message':str(exc)}), 500


@settings_bp.route('/backups', methods=['GET'])
def backups():
    return jsonify({'status':'success','backups':list_backups()})


@settings_bp.route('/restore', methods=['POST'])
def restore():
    upload = request.files.get('database')
    if not upload or not upload.filename:
        return jsonify({'status':'error','message':'Choose a SQLite database backup first.'}), 400
    temp = os.path.join(os.path.abspath(os.path.dirname(current_app.config.get('UPLOAD_FOLDER', '.'))), 'restore_upload.db')
    try:
        upload.save(temp)
        restore_database(temp)
        write_audit('database_restored', 'database', None, upload.filename)
        return jsonify({'status':'success','message':'Database restored successfully. Restarting data services is recommended.'}), 200
    except Exception as exc:
        return jsonify({'status':'error','message':str(exc)}), 400
    finally:
        try: os.remove(temp)
        except OSError: pass
