"""Dashboard - 个人系统管理首页"""
import os, sqlite3, subprocess, threading, atexit, time, shutil
from datetime import datetime, timedelta, timezone
from flask import Flask, request, jsonify, g, send_from_directory
from flask_cors import CORS
import requests
import psutil
from cryptography.fernet import Fernet
from webdav3.client import Client as WebDavClient

app = Flask(__name__, template_folder='templates')
CORS(app)
DB_PATH = os.path.join(os.path.dirname(__file__), 'config.db')

# --- 备份常量与加密 ---
KEY_DIR = os.path.expanduser('~/.dashboard')
KEY_FILE = os.path.join(KEY_DIR, '.key')
BACKUP_BASE = '/home/zhaohaosen/backup'
os.makedirs(KEY_DIR, exist_ok=True)
os.makedirs(BACKUP_BASE, exist_ok=True)

def _get_fernet():
    if not os.path.exists(KEY_FILE):
        key = Fernet.generate_key()
        with open(KEY_FILE, 'wb') as f:
            f.write(key)
        os.chmod(KEY_FILE, 0o600)
    with open(KEY_FILE, 'rb') as f:
        return Fernet(f.read())

def encrypt_password(pwd):
    return _get_fernet().encrypt(pwd.encode()).decode()

def decrypt_password(enc):
    return _get_fernet().decrypt(enc.encode()).decode()

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
    """数据库迁移：添加新字段和新表"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # systems 表迁移
    c.execute("PRAGMA table_info(systems)")
    columns = [col[1] for col in c.fetchall()]
    if 'service_name' not in columns:
        c.execute('ALTER TABLE systems ADD COLUMN service_name TEXT')
    # 备份配置字段
    for field, dtype in [('db_path', 'TEXT'), ('backup_enabled', 'INTEGER DEFAULT 0'),
                         ('backup_interval', "TEXT DEFAULT 'daily'"),
                         ('backup_keep', 'INTEGER DEFAULT 3'), ('last_backup', 'TEXT')]:
        if field not in columns:
            c.execute(f'ALTER TABLE systems ADD COLUMN {field} {dtype}')
    # wsl_metrics 表
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='wsl_metrics'")
    if not c.fetchone():
        c.execute('''CREATE TABLE wsl_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            cpu_percent REAL,
            mem_used REAL, mem_total REAL, mem_percent REAL,
            disk_used REAL, disk_total REAL, disk_percent REAL)''')
        c.execute('CREATE INDEX idx_wsl_metrics_ts ON wsl_metrics(timestamp)')
    # wsl_events 表（开机/关机事件）
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='wsl_events'")
    if not c.fetchone():
        c.execute('''CREATE TABLE wsl_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            detail TEXT)''')
        c.execute('CREATE INDEX idx_wsl_events_ts ON wsl_events(timestamp)')
    # webdav_config 表
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='webdav_config'")
    if not c.fetchone():
        c.execute('''CREATE TABLE webdav_config (
            id INTEGER PRIMARY KEY, webdav_url TEXT, username TEXT,
            password_encrypted TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    # backup_records 表
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='backup_records'")
    if not c.fetchone():
        c.execute('''CREATE TABLE backup_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT, system_id INTEGER,
            backup_file TEXT NOT NULL, backup_path TEXT NOT NULL,
            file_size INTEGER, backup_type TEXT DEFAULT 'manual',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
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
        'INSERT INTO systems (name,url,port,description,icon,color,sort_order,service_name,db_path,backup_enabled,backup_interval,backup_keep) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
        (d['name'], d['url'], d.get('port'), d.get('description',''), d.get('icon','box'),
         d.get('color','#3b82f6'), max_o+1, d.get('service_name',''),
         d.get('db_path'), d.get('backup_enabled', 0), d.get('backup_interval','daily'), d.get('backup_keep', 3)))
    db.commit()
    cur = db.execute('SELECT * FROM systems WHERE id=?', (cur.lastrowid,))
    return jsonify(dict(cur.fetchone())), 201

@app.route('/api/systems/<int:sid>', methods=['PUT'])
def update_system(sid):
    d = request.json
    db = get_db()
    db.execute(
        'UPDATE systems SET name=?,url=?,port=?,description=?,icon=?,color=?,service_name=?,db_path=?,backup_enabled=?,backup_interval=?,backup_keep=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',
        (d['name'], d['url'], d.get('port'), d.get('description',''), d.get('icon','box'),
         d.get('color','#3b82f6'), d.get('service_name',''),
         d.get('db_path'), d.get('backup_enabled', 0), d.get('backup_interval','daily'), d.get('backup_keep', 3), sid))
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

# --- WSL 性能监控 ---
METRICS_INTERVAL = 300  # 5 minutes
METRICS_RETENTION_DAYS = 30
_sampler_stop = threading.Event()

def _record_boot_event():
    """Detect and record boot event on startup."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    boot_time = datetime.fromtimestamp(psutil.boot_time(), tz=timezone.utc)
    boot_str = boot_time.strftime('%Y-%m-%dT%H:%M:%SZ')
    # Check if we already recorded a boot at this time
    c.execute('SELECT id FROM wsl_events WHERE event_type=? AND timestamp=?',
              ('boot', boot_str))
    if not c.fetchone():
        c.execute('INSERT INTO wsl_events (event_type, timestamp, detail) VALUES (?,?,?)',
                  ('boot', boot_str, 'uptime detection'))
        # Check if previous event was a shutdown; if not, insert one for the gap
        c.execute('SELECT timestamp FROM wsl_events WHERE event_type IN (?,?) ORDER BY timestamp DESC LIMIT 1',
                  ('boot', 'shutdown'))
        prev = c.fetchone()
        if prev:
            last_ts = datetime.fromisoformat(prev[0].replace('Z', '+00:00'))
            if boot_time - last_ts > timedelta(hours=1):
                # There was an unrecorded shutdown - estimate time from last metric
                c.execute('SELECT timestamp FROM wsl_metrics ORDER BY timestamp DESC LIMIT 1')
                last_metric = c.fetchone()
                if last_metric:
                    c.execute('INSERT INTO wsl_events (event_type, timestamp, detail) VALUES (?,?,?)',
                              ('shutdown', last_metric[0], 'estimated from last metric'))
        conn.commit()
    conn.close()

def _record_shutdown_event():
    """Record shutdown event on exit (best-effort)."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        c.execute('INSERT INTO wsl_events (event_type, timestamp, detail) VALUES (?,?,?)',
                  ('shutdown', now, 'graceful shutdown'))
        conn.commit()
        conn.close()
    except Exception:
        pass

def _sample_metrics():
    """Collect and store current metrics."""
    try:
        cpu = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            'INSERT INTO wsl_metrics (timestamp, cpu_percent, mem_used, mem_total, mem_percent, disk_used, disk_total, disk_percent) VALUES (?,?,?,?,?,?,?,?)',
            (ts, cpu, round(mem.used/(1024**3), 2), round(mem.total/(1024**3), 1),
             round(mem.percent, 1), round(disk.used/(1024**3), 2), round(disk.total/(1024**3), 1),
             round(disk.percent, 1)))
        conn.commit()
        conn.close()
        # Cleanup old data
        cutoff = (datetime.now(timezone.utc) - timedelta(days=METRICS_RETENTION_DAYS)).strftime('%Y-%m-%dT%H:%M:%SZ')
        conn = sqlite3.connect(DB_PATH)
        conn.execute('DELETE FROM wsl_metrics WHERE timestamp < ?', (cutoff,))
        conn.commit()
        conn.close()
    except Exception:
        pass

def _sampler_loop():
    """Background loop that samples metrics every METRICS_INTERVAL seconds."""
    _sample_metrics()  # first sample immediately
    while not _sampler_stop.wait(METRICS_INTERVAL):
        _sample_metrics()

def start_metrics_sampler():
    """Start background metrics sampler and record boot event."""
    _record_boot_event()
    atexit.register(_record_shutdown_event)
    t = threading.Thread(target=_sampler_loop, daemon=True)
    t.start()

@app.route('/api/wsl/metrics')
def wsl_metrics():
    cpu_percent = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    uptime_hours = (psutil.time.time() - psutil.boot_time()) / 3600
    if uptime_hours >= 24:
        uptime_str = f'{int(uptime_hours // 24)}d {int(uptime_hours % 24)}h'
    else:
        uptime_str = f'{uptime_hours:.1f}h'
    return jsonify({
        'cpu_percent': cpu_percent,
        'memory': {
            'total': round(mem.total / (1024**3), 1),
            'used': round(mem.used / (1024**3), 1),
            'percent': mem.percent
        },
        'disk': {
            'total': round(disk.total / (1024**3), 1),
            'used': round(disk.used / (1024**3), 1),
            'percent': round(disk.percent, 1)
        },
        'uptime': uptime_str
    })

@app.route('/api/wsl/metrics/history')
def wsl_metrics_history():
    """Return historical metrics with downsampling and events."""
    hours = request.args.get('hours', 24, type=int)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime('%Y-%m-%dT%H:%M:%SZ')
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        'SELECT timestamp, cpu_percent, mem_percent, disk_percent FROM wsl_metrics WHERE timestamp >= ? ORDER BY timestamp',
        (cutoff,)).fetchall()
    conn.close()

    # Downsample: target max ~100 points for smooth sparkline
    raw = [dict(r) for r in rows]
    max_points = 100
    if len(raw) > max_points:
        step = len(raw) / max_points
        metrics = [raw[int(i * step)] for i in range(max_points)]
    else:
        metrics = raw

    # Get events in the same time range
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    events = conn.execute(
        'SELECT event_type, timestamp FROM wsl_events WHERE timestamp >= ? ORDER BY timestamp',
        (cutoff,)).fetchall()
    conn.close()

    return jsonify({
        'metrics': metrics,
        'events': [dict(e) for e in events]
    })

@app.route('/api/wsl/events')
def wsl_events():
    """Return boot/shutdown events, most recent first."""
    limit = request.args.get('limit', 20, type=int)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        'SELECT event_type, timestamp, detail FROM wsl_events ORDER BY timestamp DESC LIMIT ?',
        (limit,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

# --- 服务控制 ---
ACTION_LABEL = {'start': '启动', 'stop': '停止', 'restart': '重启'}

def _systemctl(args, timeout=10):
    """Execute systemctl at system level (sudo)."""
    return subprocess.run(
        ['sudo', 'systemctl'] + args,
        capture_output=True, text=True, timeout=timeout, encoding='utf-8', errors='replace'
    )

def _journalctl(args, timeout=5):
    """Execute journalctl at system level (sudo)."""
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

# --- 数据备份 ---
def _get_backup_dir(system_id=None):
    """获取备份目录路径，system_id=None 表示 Dashboard 自身"""
    if system_id is None:
        return os.path.join(BACKUP_BASE, 'dashboard')
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute('SELECT service_name, name FROM systems WHERE id=?', (system_id,)).fetchone()
    conn.close()
    name = (row['service_name'] or row['name'] or f'system-{system_id}') if row else f'system-{system_id}'
    return os.path.join(BACKUP_BASE, name.replace('/', '_').replace(' ', '-'))

def _backup_filename():
    return datetime.now().strftime('%Y%m%d_%H%M%S') + '.db'

def perform_backup(system_id=None, db_path=None, backup_type='manual'):
    """执行单次备份"""
    if system_id is None:
        src = DB_PATH
        backup_dir = _get_backup_dir()
    else:
        if not db_path:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            row = conn.execute('SELECT db_path FROM systems WHERE id=?', (system_id,)).fetchone()
            conn.close()
            db_path = row['db_path'] if row else None
        if not db_path or not os.path.exists(db_path):
            raise FileNotFoundError(f'数据库文件不存在: {db_path}')
        src = db_path
        backup_dir = _get_backup_dir(system_id)
    os.makedirs(backup_dir, exist_ok=True)
    filename = _backup_filename()
    dest = os.path.join(backup_dir, filename)
    shutil.copy2(src, dest)
    size = os.path.getsize(dest)
    conn = sqlite3.connect(DB_PATH)
    conn.execute('INSERT INTO backup_records (system_id,backup_file,backup_path,file_size,backup_type) VALUES (?,?,?,?,?)',
                 (system_id, filename, dest, size, backup_type))
    if system_id is not None:
        conn.execute('UPDATE systems SET last_backup=? WHERE id=?', (datetime.now().isoformat(), system_id))
    conn.commit()
    conn.close()
    if system_id is not None:
        _cleanup_old_backups(system_id)
    return {'filename': filename, 'path': dest, 'size': size}

def _cleanup_old_backups(system_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute('SELECT backup_keep FROM systems WHERE id=?', (system_id,)).fetchone()
    keep = row['backup_keep'] if row else 3
    backups = conn.execute('SELECT id,backup_path FROM backup_records WHERE system_id=? ORDER BY created_at DESC', (system_id,)).fetchall()
    if len(backups) > keep:
        for b in backups[keep:]:
            try:
                if os.path.exists(b['backup_path']):
                    os.remove(b['backup_path'])
                conn.execute('DELETE FROM backup_records WHERE id=?', (b['id'],))
            except Exception:
                pass
    conn.commit()
    conn.close()

def _startup_backup_check():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute('SELECT id FROM systems WHERE backup_enabled=1 AND db_path IS NOT NULL').fetchall()
    conn.close()
    for row in rows:
        try:
            conn2 = sqlite3.connect(DB_PATH)
            conn2.row_factory = sqlite3.Row
            s = conn2.execute('SELECT backup_interval, last_backup FROM systems WHERE id=?', (row['id'],)).fetchone()
            conn2.close()
            interval_map = {'daily': 1, 'weekly': 7, 'monthly': 30}
            interval_days = interval_map.get(s['backup_interval'] if s else 'daily', 1)
            if s and s['last_backup']:
                if (datetime.now() - datetime.fromisoformat(s['last_backup'])).days < interval_days:
                    continue
            perform_backup(row['id'], backup_type='auto')
        except Exception:
            pass

def _startup_backup_thread():
    """后台启动备份检查（1小时防抖）"""
    stamp_file = os.path.join(KEY_DIR, '.last_backup_check')
    try:
        with open(stamp_file, 'r') as f:
            if time.time() - float(f.read().strip()) < 3600:
                return
    except (FileNotFoundError, ValueError):
        pass
    with open(stamp_file, 'w') as f:
        f.write(str(time.time()))
    _startup_backup_check()

# 备份 API
@app.route('/api/backup/list/<int:sid>')
def list_backups(sid):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute('SELECT id,backup_file,backup_path,file_size,backup_type,created_at FROM backup_records WHERE system_id=? ORDER BY created_at DESC', (sid,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/backup/list/dashboard')
def list_dashboard_backups():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute('SELECT id,backup_file,backup_path,file_size,backup_type,created_at FROM backup_records WHERE system_id IS NULL ORDER BY created_at DESC').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/backup/perform/<int:sid>', methods=['POST'])
def manual_backup(sid):
    try:
        result = perform_backup(sid, backup_type='manual')
        return jsonify({'ok': True, **result})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/backup/perform/dashboard', methods=['POST'])
def manual_backup_dashboard():
    try:
        result = perform_backup(backup_type='manual')
        return jsonify({'ok': True, **result})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

# --- 恢复功能 ---
def restore_backup(system_id=None, backup_path=None):
    if system_id is None:
        target_db = DB_PATH
        service_name = None
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute('SELECT service_name, db_path FROM systems WHERE id=?', (system_id,)).fetchone()
        conn.close()
        if not row:
            raise ValueError(f'系统 {system_id} 不存在')
        target_db = row['db_path']
        service_name = row['service_name']
    if not backup_path or not os.path.exists(backup_path):
        raise FileNotFoundError(f'备份文件不存在: {backup_path}')
    if service_name:
        _systemctl(['stop', service_name])
        time.sleep(1)
    pre_name = 'pre_restore_' + _backup_filename()
    pre_path = os.path.join(os.path.dirname(backup_path), pre_name)
    shutil.copy2(target_db, pre_path)
    shutil.copy2(backup_path, target_db)
    if service_name:
        _systemctl(['start', service_name])
    return {'ok': True, 'pre_restore': pre_path, 'restored_from': backup_path}

@app.route('/api/restore/perform/<int:sid>', methods=['POST'])
def perform_restore(sid):
    backup_path = request.json.get('backup_path')
    if not backup_path:
        return jsonify({'ok': False, 'error': '缺少 backup_path'}), 400
    try:
        result = restore_backup(sid, backup_path)
        return jsonify(result)
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/restore/perform/dashboard', methods=['POST'])
def perform_restore_dashboard():
    backup_path = request.json.get('backup_path')
    if not backup_path:
        return jsonify({'ok': False, 'error': '缺少 backup_path'}), 400
    try:
        result = restore_backup(backup_path=backup_path)
        return jsonify(result)
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

# --- WebDAV ---
def _get_webdav_client():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute('SELECT * FROM webdav_config LIMIT 1').fetchone()
    conn.close()
    if not row or not row['webdav_url']:
        raise ValueError('WebDAV 未配置')
    return WebDavClient({
        'webdav_hostname': row['webdav_url'],
        'webdav_root': '/',
        'webdav_login': row['username'],
        'webdav_password': decrypt_password(row['password_encrypted']),
        'disable_check': True
    })

@app.route('/api/webdav/config', methods=['GET'])
def get_webdav_config():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute('SELECT * FROM webdav_config LIMIT 1').fetchone()
    conn.close()
    if not row:
        return jsonify({'configured': False})
    return jsonify({'configured': True, 'webdav_url': row['webdav_url'], 'username': row['username'], 'password': ''})

@app.route('/api/webdav/config', methods=['POST'])
def save_webdav_config():
    d = request.json
    enc_pwd = encrypt_password(d['password']) if d.get('password') else None
    conn = sqlite3.connect(DB_PATH)
    existing = conn.execute('SELECT id FROM webdav_config LIMIT 1').fetchone()
    if existing:
        conn.execute('UPDATE webdav_config SET webdav_url=?,username=?,password_encrypted=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',
                     (d['webdav_url'], d['username'], enc_pwd, existing[0]))
    else:
        conn.execute('INSERT INTO webdav_config (webdav_url,username,password_encrypted) VALUES (?,?,?)',
                     (d['webdav_url'], d['username'], enc_pwd))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/webdav/check', methods=['POST'])
def check_webdav():
    try:
        client = _get_webdav_client()
        client.list()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

def _webdav_remote_dir(system_id=None):
    """获取云端的远程目录路径，按系统名分目录"""
    if system_id is None:
        return '/dashboard/dashboard/'
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute('SELECT service_name FROM systems WHERE id=?', (system_id,)).fetchone()
    conn.close()
    name = row['service_name'] if row else str(system_id)
    return f'/dashboard/{name}/'

@app.route('/api/webdav/list')
def list_webdav_files():
    """列出云端指定系统目录的文件"""
    system_id = request.args.get('system_id', type=int)  # None=dashboard
    remote_dir = _webdav_remote_dir(system_id)
    try:
        client = _get_webdav_client()
        try:
            files = client.list(remote_dir)
        except Exception:
            files = []
        result = []
        for f in files:
            name = f.split('/')[-1] if '/' in f else f
            if name and not f.endswith('/'):
                result.append({'name': name, 'path': remote_dir + name})
        return jsonify({'ok': True, 'files': result})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/webdav/upload', methods=['POST'])
def upload_to_webdav():
    d = request.json
    local_path = d.get('local_path')
    remote_path = d.get('remote_path')
    system_id = d.get('system_id')  # None=dashboard
    if not local_path or not os.path.exists(local_path):
        return jsonify({'ok': False, 'error': '本地文件不存在'}), 400
    try:
        client = _get_webdav_client()
        filename = remote_path or os.path.basename(local_path)
        remote_dir = _webdav_remote_dir(system_id)
        client.mkdir(remote_dir)
        client.upload_sync(remote_path=remote_dir + filename, local_path=local_path)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/webdav/download', methods=['POST'])
def download_from_webdav():
    """从云端下载备份文件，支持下载后恢复"""
    d = request.json
    remote_path = d.get('remote_path')
    system_id = d.get('system_id')  # None=dashboard
    do_restore = d.get('restore', False)
    if not remote_path:
        return jsonify({'ok': False, 'error': '缺少 remote_path'}), 400

    # 确定本地备份目录和目标数据库
    if system_id is None:
        backup_dir = os.path.join(BACKUP_BASE, 'dashboard')
        target_db = DB_PATH
        service_name = None
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute('SELECT service_name, db_path FROM systems WHERE id=?', (system_id,)).fetchone()
        conn.close()
        if not row:
            return jsonify({'ok': False, 'error': '系统不存在'}), 400
        backup_dir = os.path.join(BACKUP_BASE, row['service_name'])
        target_db = row['db_path']
        service_name = row['service_name']
    os.makedirs(backup_dir, exist_ok=True)

    local_path = os.path.join(backup_dir, os.path.basename(remote_path))
    try:
        client = _get_webdav_client()
        client.download_sync(remote_path=remote_path, local_path=local_path)

        if do_restore:
            # 先停止服务
            if service_name:
                _systemctl(['stop', service_name])
                time.sleep(1)
            # 预恢复快照
            pre_name = 'pre_restore_' + _backup_filename()
            pre_path = os.path.join(backup_dir, pre_name)
            shutil.copy2(target_db, pre_path)
            # 恢复
            shutil.copy2(local_path, target_db)
            # 重启服务
            if service_name:
                _systemctl(['start', service_name])
            return jsonify({'ok': True, 'restored': True, 'local_path': local_path})

        return jsonify({'ok': True, 'local_path': local_path})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

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
    start_metrics_sampler()
    threading.Thread(target=_startup_backup_thread, daemon=True).start()
    app.run(host='0.0.0.0', port=8850, debug=True)
