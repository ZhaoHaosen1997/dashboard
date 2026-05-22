"""System management routes - CRUD, service control, logs."""
import requests
from flask import Blueprint, request, jsonify

from config import CFG
from db import get_db
from utils import _systemctl, _journalctl

systems_bp = Blueprint('systems', __name__)

ACTION_LABEL = CFG['service_labels']


@systems_bp.route('/api/systems')
def get_systems():
    db = get_db()
    cur = db.execute('SELECT * FROM systems ORDER BY sort_order, id')
    return jsonify([dict(r) for r in cur.fetchall()])


@systems_bp.route('/api/systems', methods=['POST'])
def create_system():
    d = request.json
    db = get_db()
    cur = db.execute('SELECT MAX(sort_order) FROM systems')
    max_o = cur.fetchone()[0] or 0
    cur = db.execute(
        'INSERT INTO systems (name,url,port,description,icon,color,sort_order,service_name,db_path,backup_enabled,backup_interval,backup_keep) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
        (d['name'], d['url'], d.get('port'), d.get('description', ''), d.get('icon', 'box'),
         d.get('color', '#3b82f6'), max_o + 1, d.get('service_name', ''),
         d.get('db_path'), d.get('backup_enabled', 0),
         d.get('backup_interval', CFG['backup']['default_interval']),
         d.get('backup_keep', CFG['backup']['default_keep'])))
    db.commit()
    cur = db.execute('SELECT * FROM systems WHERE id=?', (cur.lastrowid,))
    return jsonify(dict(cur.fetchone())), 201


@systems_bp.route('/api/systems/<int:sid>', methods=['PUT'])
def update_system(sid):
    d = request.json
    db = get_db()
    db.execute(
        'UPDATE systems SET name=?,url=?,port=?,description=?,icon=?,color=?,service_name=?,db_path=?,backup_enabled=?,backup_interval=?,backup_keep=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',
        (d['name'], d['url'], d.get('port'), d.get('description', ''), d.get('icon', 'box'),
         d.get('color', '#3b82f6'), d.get('service_name', ''),
         d.get('db_path'), d.get('backup_enabled', 0),
         d.get('backup_interval', CFG['backup']['default_interval']),
         d.get('backup_keep', CFG['backup']['default_keep']), sid))
    db.commit()
    cur = db.execute('SELECT * FROM systems WHERE id=?', (sid,))
    return jsonify(dict(cur.fetchone()))


@systems_bp.route('/api/systems/<int:sid>', methods=['DELETE'])
def delete_system(sid):
    db = get_db()
    db.execute('DELETE FROM systems WHERE id=?', (sid,))
    db.commit()
    return jsonify({'ok': True})


@systems_bp.route('/api/systems/reorder', methods=['PATCH'])
def reorder():
    db = get_db()
    for item in request.json.get('orders', []):
        db.execute('UPDATE systems SET sort_order=? WHERE id=?', (item['sort_order'], item['id']))
    db.commit()
    return jsonify({'ok': True})


@systems_bp.route('/api/systems/<int:sid>/status')
def check_status(sid):
    db = get_db()
    cur = db.execute('SELECT url FROM systems WHERE id=?', (sid,))
    row = cur.fetchone()
    if not row:
        return jsonify({'error': 'Not found'}), 404
    try:
        r = requests.head(row['url'], timeout=CFG['timeout']['status_check'])
        online = r.status_code < 500
    except Exception:
        online = False
    return jsonify({'id': sid, 'online': online})


@systems_bp.route('/api/systems/<int:sid>/service/<action>', methods=['POST'])
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
    except Exception as e:
        return jsonify({'ok': False, 'message': str(e)}), 500


@systems_bp.route('/api/systems/<int:sid>/logs')
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
