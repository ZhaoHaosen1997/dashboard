"""Local backup and restore routes."""
import sqlite3
from flask import Blueprint, request, jsonify

from db import DB_PATH
from utils import perform_backup, restore_backup

backup_bp = Blueprint('backup', __name__)


@backup_bp.route('/api/backup/list/<int:sid>')
def list_backups(sid):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        'SELECT id,backup_file,backup_path,file_size,backup_type,created_at FROM backup_records WHERE system_id=? ORDER BY created_at DESC',
        (sid,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@backup_bp.route('/api/backup/list/dashboard')
def list_dashboard_backups():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        'SELECT id,backup_file,backup_path,file_size,backup_type,created_at FROM backup_records WHERE system_id IS NULL ORDER BY created_at DESC'
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@backup_bp.route('/api/backup/perform/<int:sid>', methods=['POST'])
def manual_backup(sid):
    try:
        result = perform_backup(sid, backup_type='manual')
        return jsonify({'ok': True, **result})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@backup_bp.route('/api/backup/perform/dashboard', methods=['POST'])
def manual_backup_dashboard():
    try:
        result = perform_backup(backup_type='manual')
        return jsonify({'ok': True, **result})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@backup_bp.route('/api/restore/perform/<int:sid>', methods=['POST'])
def perform_restore(sid):
    backup_path = request.json.get('backup_path')
    if not backup_path:
        return jsonify({'ok': False, 'error': '缺少 backup_path'}), 400
    try:
        result = restore_backup(sid, backup_path)
        return jsonify(result)
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@backup_bp.route('/api/restore/perform/dashboard', methods=['POST'])
def perform_restore_dashboard():
    backup_path = request.json.get('backup_path')
    if not backup_path:
        return jsonify({'ok': False, 'error': '缺少 backup_path'}), 400
    try:
        result = restore_backup(backup_path=backup_path)
        return jsonify(result)
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
