import atexit
import logging
from logging.handlers import RotatingFileHandler
import multiprocessing
import os
import socket
import sys
import threading
import time

import webview
from flask import Flask, redirect, render_template, request, send_from_directory, session, url_for
from zeroconf import ServiceInfo, Zeroconf

from db import get_default_db_dir, load_config, get_app_data_dir, init_db, purge_old_logs, backup_database, write_audit
from routes.api import api_bp, process_auto_checkouts
from routes.auth import auth_bp
from routes.settings import settings_bp


APP_HOST = "0.0.0.0"
APP_PORT = 5001
APP_VERSION = "2.2.3"
LOCAL_URL = f"http://127.0.0.1:{APP_PORT}"


def configure_logging():
    log_dir = os.path.join(get_app_data_dir(), "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "mecatech-pointage.log")
    handler = RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(isinstance(h, RotatingFileHandler) and getattr(h, "baseFilename", "") == os.path.abspath(log_file) for h in root.handlers):
        root.addHandler(handler)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    return logging.getLogger("mecatech")


logger = configure_logging()


def resource_path(*parts):
    if getattr(sys, "frozen", False):
        root = sys._MEIPASS
    else:
        root = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(root, *parts)


app = Flask(
    __name__,
    template_folder=resource_path("templates"),
    static_folder=resource_path("static"),
)

# Flask sessions are local to this application. Do not expose this secret publicly.
app.secret_key = os.environ.get("MECATECH_SESSION_SECRET") or os.urandom(32)
app.config.update(
    MAX_CONTENT_LENGTH=1 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=False,
    PERMANENT_SESSION_LIFETIME=8 * 60 * 60,
)


@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.errorhandler(413)
def request_too_large(_error):
    return {"status": "error", "message": "Request is too large."}, 413


@app.errorhandler(Exception)
def handle_unexpected_error(error):
    logger.exception("Unhandled application error: %s", error)
    if request.path.startswith("/api/"):
        return {"status": "error", "message": "Internal application error."}, 500
    return "Internal application error.", 500


def configure_upload_folder():
    cfg = load_config()
    data_dir = os.path.abspath(os.path.expanduser(cfg.get("db_path") or get_default_db_dir()))
    upload_folder = os.path.join(data_dir, "uploads")
    os.makedirs(upload_folder, exist_ok=True)
    app.config["UPLOAD_FOLDER"] = upload_folder


configure_upload_folder()

app.register_blueprint(api_bp, url_prefix="/api")
app.register_blueprint(auth_bp, url_prefix="/auth")
app.register_blueprint(settings_bp, url_prefix="/api/settings")


@app.route("/uploads/<path:filename>")
def serve_uploads(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


@app.before_request
def require_login():
    allowed_routes = {
        "auth.login",
        "static",
        "api.heartbeat",
        "api.api_scan",
        "serve_uploads",
        "health",
        "api_health",
    }
    if not session.get("logged_in") and request.endpoint not in allowed_routes:
        return redirect(url_for("auth.login"))


@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok", "service": "mecatech-pointage", "version": APP_VERSION}, 200


@app.route("/api/health", methods=["GET"])
def api_health():
    return {"status": "ok", "service": "mecatech-pointage", "version": APP_VERSION}, 200


@app.route("/")
def index():
    cfg = load_config()
    return render_template("dashboard/index.html", cfg=cfg)


def get_local_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


_mdns = None


def register_mdns():
    global _mdns
    try:
        hostname = socket.gethostname()
        local_ip = get_local_ip()
        service_name = f"{hostname}._mecatech._tcp.local."

        info = ServiceInfo(
            "_mecatech._tcp.local.",
            service_name,
            addresses=[socket.inet_aton(local_ip)],
            port=APP_PORT,
            properties={"path": "/api/scan"},
            server=f"{hostname}.local.",
        )

        _mdns = Zeroconf()
        _mdns.register_service(info)

        def close_mdns():
            global _mdns
            if _mdns is not None:
                try:
                    _mdns.unregister_all_services()
                    _mdns.close()
                except Exception:
                    pass
                _mdns = None

        atexit.register(close_mdns)
    except Exception as exc:
        # mDNS is optional. The desktop application must still start if discovery fails.
        logger.warning("mDNS discovery registration unavailable: %s", exc)
        _mdns = None


def run_flask():
    # Waitress is a production WSGI server suitable for a packaged Windows desktop application.
    from waitress import serve
    logger.info("Starting WSGI server on %s:%s", APP_HOST, APP_PORT)
    serve(
        app,
        host=APP_HOST,
        port=APP_PORT,
        threads=8,
        connection_limit=100,
        channel_timeout=30,
        cleanup_interval=10,
        ident="MecatechPointage",
    )


MAINTENANCE_INTERVAL_SECONDS = 5
_maintenance_thread = None
_maintenance_lock = threading.Lock()
_maintenance_wakeup = threading.Event()


def maintenance_worker():
    """Run attendance maintenance continuously, independently of ESP32 traffic."""
    last_purge = 0.0
    last_backup = 0.0
    while True:
        started = time.monotonic()
        try:
            closed = process_auto_checkouts()
            if closed:
                logger.info("Auto check-out closed %d worker(s).", closed)
                try:
                    write_audit('auto_checkout', 'attendance', None, f'Automatically closed {closed} open attendance record(s).')
                except Exception:
                    logger.exception("Failed to write auto check-out audit event")
            if started - last_purge >= 300:
                purge_old_logs()
                last_purge = started
            if started - last_backup >= 86400:
                backup_database()
                last_backup = started
        except Exception as exc:
            logger.exception("Maintenance cycle failed: %s", exc)
        # Wake immediately when settings are changed, otherwise poll every 5 s.
        _maintenance_wakeup.wait(MAINTENANCE_INTERVAL_SECONDS)
        _maintenance_wakeup.clear()


def start_maintenance_worker():
    """Start exactly one maintenance thread for this application process."""
    global _maintenance_thread
    with _maintenance_lock:
        if _maintenance_thread is not None and _maintenance_thread.is_alive():
            return
        _maintenance_thread = threading.Thread(
            target=maintenance_worker,
            name="Mecatech-Maintenance",
            daemon=True,
        )
        _maintenance_thread.start()
        logger.info("Attendance maintenance worker started.")


def wake_maintenance_worker():
    start_maintenance_worker()
    _maintenance_wakeup.set()


@app.before_request
def ensure_maintenance_worker():
    # This also covers running the Flask app through a WSGI/CLI entry point
    # instead of the normal pywebview main().
    start_maintenance_worker()


def ensure_port_available(host="127.0.0.1", port=APP_PORT):
    """Fail fast when another application already owns the fixed ESP service port."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        result = probe.connect_ex((host, port))
        if result == 0:
            raise RuntimeError(
                f"Mecatech Pointage cannot start because TCP port {port} is already in use. "
                "Close the other instance/application using that port and try again."
            )
    finally:
        probe.close()


def wait_for_server(timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", APP_PORT), timeout=0.25):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def main():
    multiprocessing.freeze_support()
    init_db()
    logger.info("Starting Mecatech Pointage v%s", APP_VERSION)
    register_mdns()

    ensure_port_available()
    flask_thread = threading.Thread(target=run_flask, name="Mecatech-Flask", daemon=True)
    flask_thread.start()

    try:
        backup_database()
    except Exception as exc:
        logger.exception("Initial database backup failed: %s", exc)

    start_maintenance_worker()

    if not wait_for_server():
        logger.error("Local server failed to start on port %s", APP_PORT)
        raise RuntimeError(f"Mecatech Pointage could not start its local server on port {APP_PORT}.")

    cfg = load_config()
    title = cfg.get("app_name") or "Mecatech Pointage"

    window = webview.create_window(
        title,
        LOCAL_URL,
        width=1280,
        height=768,
        min_size=(360, 560),
        resizable=True,
        text_select=True,
    )

    # pywebview owns the visible desktop window. Closing it ends the GUI process.
    try:
        webview.start(debug=False)
    finally:
        logger.info("Mecatech Pointage window closed")


if __name__ == "__main__":
    main()
