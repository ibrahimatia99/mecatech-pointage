import os
import platform
from flask import Blueprint, request, jsonify, current_app, url_for
from werkzeug.utils import secure_filename
from db import load_config, save_config

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

@settings_bp.route('/update', methods=['POST'])
def update_settings():
    try:
        cfg = load_config()
        
        cfg['db_path'] = request.form.get('db_path', cfg.get('db_path'))
        cfg['app_name'] = request.form.get('app_name', cfg.get('app_name'))
        cfg['app_password'] = request.form.get('app_password', cfg.get('app_password'))
        cfg['theme'] = request.form.get('theme', cfg.get('theme'))
        cfg['primary_color'] = request.form.get('primary_color', cfg.get('primary_color'))
        
        purge = request.form.get('purge_days')
        if purge and purge.isdigit():
            cfg['purge_days'] = int(purge)

        upload_dir = current_app.config['UPLOAD_FOLDER']

        if 'app_logo' in request.files:
            file = request.files['app_logo']
            if file and file.filename != '':
                filename = 'logo_' + secure_filename(file.filename)
                file.save(os.path.join(upload_dir, filename))
                cfg['app_logo'] = url_for('static', filename='uploads/' + filename)

        if 'app_icon' in request.files:
            file = request.files['app_icon']
            if file and file.filename != '':
                filename = 'icon_' + secure_filename(file.filename)
                file.save(os.path.join(upload_dir, filename))
                cfg['app_icon'] = url_for('static', filename='uploads/' + filename)

        save_config(cfg)
        return jsonify({"status": "updated"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500