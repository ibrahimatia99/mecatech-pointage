from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify
from db import load_config

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

        expected_password = cfg.get('app_password', 'admin')

        if password == expected_password:
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