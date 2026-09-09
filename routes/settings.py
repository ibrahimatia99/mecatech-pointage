import os
import sys
import subprocess
import platform
from flask import Blueprint, request, jsonify, current_app, url_for
from werkzeug.utils import secure_filename
from db import load_config, save_config

settings_bp = Blueprint('settings', __name__)

@settings_bp.route('/choose-directory', methods=['POST'])
def choose_directory():
    try:
        selected_dir = ""

        if platform.system() == "Darwin":
            cmd = 'osascript -e "POSIX path of (choose folder with prompt \\"Select Database Storage Directory\\")"'
            process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, _ = process.communicate()
            selected_dir = stdout.decode('utf-8').strip()

        elif platform.system() == "Windows":
            python_script = (
                "import tkinter as tk; "
                "from tkinter import filedialog; "
                "root = tk.Tk(); "
                "root.withdraw(); "
                "root.attributes('-topmost', True); "
                "path = filedialog.askdirectory(title='Select Database Storage Directory'); "
                "print(path); "
                "root.destroy()"
            )
            process = subprocess.Popen(
                [sys.executable, "-c", python_script],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            stdout, _ = process.communicate()
            selected_dir = stdout.strip()

        else:
            python_script = (
                "import tkinter as tk; "
                "from tkinter import filedialog; "
                "root = tk.Tk(); "
                "root.withdraw(); "
                "path = filedialog.askdirectory(); "
                "print(path)"
            )
            process = subprocess.Popen([sys.executable, "-c", python_script], stdout=subprocess.PIPE, text=True)
            stdout, _ = process.communicate()
            selected_dir = stdout.strip()

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