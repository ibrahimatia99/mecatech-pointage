from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify
from db import load_config, save_config

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    cfg = load_config()
    error = None

    # If already logged in, redirect directly to the main dashboard
    if session.get('logged_in') and request.method == 'GET':
        return redirect(url_for('index'))

    if request.method == 'POST':
        # Accept credentials from standard HTML form submissions or JSON requests
        if request.is_json:
            data = request.get_json() or {}
            password = data.get('password', '')
        else:
            password = request.form.get('password', '')

        stored_password = cfg.get('app_password', 'admin')
        valid = False
        is_hash = isinstance(stored_password, str) and stored_password.startswith(('pbkdf2:', 'scrypt:'))
        if is_hash:
            from werkzeug.security import check_password_hash
            try:
                valid = check_password_hash(stored_password, password)
            except ValueError:
                valid = False
        else:
            # Backward-compatible migration from legacy plaintext configuration.
            valid = password == stored_password
            if valid:
                from werkzeug.security import generate_password_hash
                cfg['app_password'] = generate_password_hash(password)
                save_config(cfg)

        if valid:
            session.clear()
            session.permanent = True
            session['logged_in'] = True
            
            if request.is_json:
                return jsonify({"status": "success", "redirect": url_for('index')}), 200
            
            return redirect(url_for('index'))
        else:
            error = "Invalid password. Please try again."
            if request.is_json:
                return jsonify({"status": "error", "message": error}), 401

    return render_template('auth/login.html', cfg=cfg, error=error)

@auth_bp.route('/logout', methods=['GET', 'POST'])
def logout():
    session.pop('logged_in', None)
    
    if request.is_json:
        return jsonify({"status": "success", "redirect": url_for('auth.login')}), 200
        
    return redirect(url_for('auth.login'))