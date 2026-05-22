"""Dashboard Flask application factory."""
import os
import threading

from flask import Flask, send_from_directory
from flask_cors import CORS

from config import CFG
from db import init_db, close_db
from routes import systems_bp, wsl_bp, backup_bp, webdav_bp, net_bp
from routes.wsl import start_metrics_sampler
from net_collector import start_net_collector
from utils import _startup_backup_thread, KEY_DIR, BACKUP_BASE

# Project root (parent of backend/)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def create_app():
    app = Flask(__name__,
                template_folder=os.path.join(PROJECT_ROOT, 'templates'),
                static_folder=os.path.join(PROJECT_ROOT, 'static'),
                static_url_path='/static')
    CORS(app)
    app.teardown_appcontext(close_db)

    # Register blueprints
    app.register_blueprint(systems_bp)
    app.register_blueprint(wsl_bp)
    app.register_blueprint(backup_bp)
    app.register_blueprint(webdav_bp)
    app.register_blueprint(net_bp)

    # Ensure required directories exist
    os.makedirs(KEY_DIR, exist_ok=True)
    os.makedirs(BACKUP_BASE, exist_ok=True)

    # Initialize database and start background tasks
    init_db(app)
    start_metrics_sampler()
    start_net_collector()
    threading.Thread(target=_startup_backup_thread, daemon=True).start()

    # --- Page routes ---
    @app.route('/favicon.ico')
    def favicon():
        return send_from_directory(PROJECT_ROOT, 'favicon.ico', mimetype='image/x-icon')

    @app.route('/')
    def index():
        return send_from_directory(os.path.join(PROJECT_ROOT, 'templates'), 'index.html')

    @app.route('/manage')
    def manage():
        return send_from_directory(os.path.join(PROJECT_ROOT, 'templates'), 'manage.html')

    return app
