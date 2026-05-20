"""Dashboard - Personal system management homepage."""
import os
import threading

from flask import Flask, send_from_directory
from flask_cors import CORS

from config import CFG
from db import init_db, close_db
from routes import systems_bp, wsl_bp, backup_bp, webdav_bp
from routes.wsl import start_metrics_sampler
from utils import _startup_backup_thread, KEY_DIR, BACKUP_BASE

app = Flask(__name__, template_folder='templates')
CORS(app)
app.teardown_appcontext(close_db)

# Register blueprints
app.register_blueprint(systems_bp)
app.register_blueprint(wsl_bp)
app.register_blueprint(backup_bp)
app.register_blueprint(webdav_bp)

# Ensure required directories exist
os.makedirs(KEY_DIR, exist_ok=True)
os.makedirs(BACKUP_BASE, exist_ok=True)

# Initialize database and start background tasks
init_db(app)
start_metrics_sampler()
threading.Thread(target=_startup_backup_thread, daemon=True).start()


# --- Page routes ---
@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.dirname(__file__), 'favicon.ico', mimetype='image/x-icon')


@app.route('/')
def index():
    return send_from_directory(os.path.dirname(__file__), 'templates/index.html')


@app.route('/manage')
def manage():
    return send_from_directory(os.path.dirname(__file__), 'templates/manage.html')


if __name__ == '__main__':
    app.run(host=CFG['server']['host'], port=CFG['server']['port'], debug=CFG['server']['debug'])
