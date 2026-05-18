"""Dashboard - 个人系统管理首页"""
import os, sqlite3, subprocess
from flask import Flask, request, jsonify, g, send_from_directory
from flask_cors import CORS
import requests

app = Flask(__name__, template_folder='templates')
CORS(app)
DB_PATH = os.path.join(os.path.dirname(__file__), 'config.db')

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(e):
    db = g.pop('db', None)
    if db: db.close()

def migrate_db():
    """数据库迁移：添加新字段"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("PRAGMA table_info(systems)")
    columns = [col[1] for col in c.fetchall()]
    if 'service_name' not in columns:
        c.execute('ALTER TABLE systems ADD COLUMN service_name TEXT')
        conn.commit()
    conn.close()

def init_db():
    if os.path.exists(DB_PATH):
        migrate_db()
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE systems (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, url TEXT NOT NULL,
        port INTEGER, description TEXT, icon TEXT DEFAULT 'box', color TEXT DEFAULT '#3b82f6',
        sort_order INTEGER DEFAULT 0, is_active INTEGER DEFAULT 1,
        service_name TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    defaults = [
        ('PrintFlow-3D', 'http://localhost:8848', 8848, '3D打印副业管理系统', 'printer', '#10b981', 1, 'printflow-3d'),
        ('Usage Data Viewer', 'http://localhost:8849', 8849, '字节API使用量查看', 'bar-chart-2', '#f59e0b', 2, 'usage-data-viewer')]
    for d in defaults:
        c.execute('INSERT INTO systems (name,url,port,description,icon,color,sort_order,service_name) VALUES (?,?,?,?,?,?,?,?)', d)
    conn.commit(); conn.close()

@app.route('/api/systems')
def get_systems():
    db = get_db()
    cur = db.execute('SELECT * FROM systems ORDER BY sort_order, id')
    return jsonify([dict(r) for r in cur.fetchall()])

@app.route('/api/systems', methods=['POST'])
def create_system():
    d = request.json
    db = get_db()
    cur = db.execute('SELECT MAX(sort_order) FROM systems')
    max_o = cur.fetchone()[0] or 0
    cur = db.execute(
        'INSERT INTO systems (name,url,port,description,icon,color,sort_order,service_name) VALUES (?,?,?,?,?,?,?,?)',
        (d['name'], d['url'], d.get('port'), d.get('description',''), d.get('icon','box'),
         d.get('color','#3b82f6'), max_o+1, d.get('service_name','')))
    db.commit()
    cur = db.execute('SELECT * FROM systems WHERE id=?', (cur.lastrowid,))
    return jsonify(dict(cur.fetchone())), 201

@app.route('/api/systems/<int:sid>', methods=['PUT'])
def update_system(sid):
    d = request.json
    db = get_db()
    db.execute(
        'UPDATE systems SET name=?,url=?,port=?,description=?,icon=?,color=?,service_name=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',
        (d['name'], d['url'], d.get('port'), d.get('description',''), d.get('icon','box'),
         d.get('color','#3b82f6'), d.get('service_name',''), sid))
    db.commit()
    cur = db.execute('SELECT * FROM systems WHERE id=?', (sid,))
    return jsonify(dict(cur.fetchone()))

@app.route('/api/systems/<int:sid>', methods=['DELETE'])
def delete_system(sid):
    db = get_db()
    db.execute('DELETE FROM systems WHERE id=?', (sid,))
    db.commit()
    return jsonify({'ok': True})

@app.route('/api/systems/reorder', methods=['PATCH'])
def reorder():
    db = get_db()
    for item in request.json.get('orders', []):
        db.execute('UPDATE systems SET sort_order=? WHERE id=?', (item['sort_order'], item['id']))
    db.commit()
    return jsonify({'ok': True})

@app.route('/api/systems/<int:sid>/status')
def check_status(sid):
    db = get_db()
    cur = db.execute('SELECT url FROM systems WHERE id=?', (sid,))
    row = cur.fetchone()
    if not row: return jsonify({'error': 'Not found'}), 404
    try:
        r = requests.head(row['url'], timeout=3)
        online = r.status_code < 500
    except: online = False
    return jsonify({'id': sid, 'online': online})

# --- 服务控制 ---
ACTION_LABEL = {'start': '启动', 'stop': '停止', 'restart': '重启'}

def _user_env():
    """Build env with D-Bus variables so systemctl --user works from system service."""
    env = os.environ.copy()
    uid = os.getuid()
    env['XDG_RUNTIME_DIR'] = f'/run/user/{uid}'
    env['DBUS_SESSION_BUS_ADDRESS'] = f'unix:path=/run/user/{uid}/bus'
    return env

def _systemctl(args, timeout=10):
    """Try systemctl --user first, fallback to sudo systemctl (system-level)."""
    env = _user_env()
    # Try user-level service
    result = subprocess.run(
        ['systemctl', '--user'] + args,
        capture_output=True, text=True, timeout=timeout, encoding='utf-8', errors='replace',
        env=env
    )
    if result.returncode == 0 or 'not loaded' not in result.stderr:
        return result
    # Fallback to system-level service
    return subprocess.run(
        ['sudo', 'systemctl'] + args,
        capture_output=True, text=True, timeout=timeout, encoding='utf-8', errors='replace'
    )

def _journalctl(args, timeout=5):
    """Try journalctl --user first, fallback to system-level."""
    env = _user_env()
    result = subprocess.run(
        ['journalctl', '--user'] + args,
        capture_output=True, text=True, timeout=timeout, encoding='utf-8', errors='replace',
        env=env
    )
    if result.returncode == 0 and result.stdout.strip() != '-- No entries --':
        return result
    # Fallback to system-level
    return subprocess.run(
        ['sudo', 'journalctl'] + args,
        capture_output=True, text=True, timeout=timeout, encoding='utf-8', errors='replace'
    )

@app.route('/api/systems/<int:sid>/service/<action>', methods=['POST'])
def service_control(sid, action):
    if action not in ACTION_LABEL:
        return jsonify({'error': '无效操作'}), 400
    db = get_db()
    row = db.execute('SELECT service_name FROM systems WHERE id=?', (sid,)).fetchone()
    if not row or not row['service_name']:
        return jsonify({'error': '该系统未配置服务名称'}), 400
    try:
        result = _systemctl([action, row['service_name']])
        if result.returncode == 0:
            return jsonify({'ok': True, 'message': f'服务已{ACTION_LABEL[action]}'})
        return jsonify({'ok': False, 'message': result.stderr.strip()}), 500
    except subprocess.TimeoutExpired:
        return jsonify({'ok': False, 'message': '操作超时'}), 500
    except Exception as e:
        return jsonify({'ok': False, 'message': str(e)}), 500

@app.route('/api/systems/<int:sid>/logs')
def service_logs(sid):
    db = get_db()
    row = db.execute('SELECT service_name FROM systems WHERE id=?', (sid,)).fetchone()
    if not row or not row['service_name']:
        return jsonify({'error': '该系统未配置服务名称'}), 400
    lines = request.args.get('lines', 50, type=int)
    try:
        result = _journalctl(['-u', row['service_name'], '-n', str(lines), '--no-pager'])
        return jsonify({'service': row['service_name'], 'logs': result.stdout})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- 页面路由 ---
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
    init_db()
    app.run(host='0.0.0.0', port=8850, debug=True)
