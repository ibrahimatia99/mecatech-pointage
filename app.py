import os
import sys
import socket
import atexit
import multiprocessing
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory
from zeroconf import ServiceInfo, Zeroconf
from db import load_config, get_default_db_dir
from routes.api import api_bp
from routes.auth import auth_bp
from routes.settings import settings_bp

# 1. Windows PyInstaller Path Resolution
if getattr(sys, 'frozen', False):
    base_dir = sys._MEIPASS
else:
    base_dir = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__, 
            template_folder=os.path.join(base_dir, 'templates'),
            static_folder=os.path.join(base_dir, 'static'))
            
app.secret_key = 'mecatech_secret_key'

# 2. Persistent Uploads Configuration
persistent_data_dir = load_config().get("db_path", get_default_db_dir())
UPLOAD_FOLDER = os.path.join(persistent_data_dir, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

app.register_blueprint(api_bp, url_prefix='/api')
app.register_blueprint(auth_bp, url_prefix='/auth')
app.register_blueprint(settings_bp, url_prefix='/api/settings')

# 3. Intercept Static Uploads Route
@app.route('/static/uploads/<filename>')
def serve_uploads(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.before_request
def require_login():
    """Restricts access to app routes if not authenticated."""
    allowed_routes = ['auth.login', 'static', 'api.heartbeat', 'api.api_scan', 'serve_uploads']
    if not session.get('logged_in') and request.endpoint not in allowed_routes:
        return redirect(url_for('auth.login'))

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

def register_mdns():
    try:
        hostname = socket.gethostname()
        local_ip = get_local_ip()
        desc = {'path': '/api/scan'}
        
        info = ServiceInfo(
            "_mecatech._tcp.local.",
            f"{hostname}._mecatech._tcp.local.",
            addresses=[socket.inet_aton(local_ip)], 
            port=5001,
            properties=desc,
            server=f"{hostname}.local."
        )
        zeroconf = Zeroconf()
        zeroconf.register_service(info)
        atexit.register(zeroconf.close)
        print(f"✅ mDNS Service Advertised: {local_ip}:5001 (_mecatech._tcp)")
    except Exception as e:
        print(f"⚠️ mDNS registration warning: {e}")

@app.route('/')
def index():
    cfg = load_config()
    return render_template('dashboard/index.html', cfg=cfg)

if __name__ == '__main__':
    # 4. Mandatory for Windows Executables
    multiprocessing.freeze_support()
    register_mdns()
    # 5. Disable Debug Reloader
    app.run(debug=False, host='0.0.0.0', port=5001)