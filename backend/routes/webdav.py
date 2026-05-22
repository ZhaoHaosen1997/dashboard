"""WebDAV cloud backup routes."""
import os
import time
import shutil
import sqlite3
from flask import Blueprint, request, jsonify
from webdav3.client import Client as WebDavClient

from config import CFG
from db import DB_PATH
from utils import encrypt_password, decrypt_password, _systemctl, _backup_filename, BACKUP_BASE

webdav_bp = Blueprint('webdav', __name__)


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


def _webdav_remote_dir(system_id=None):
    """Get remote cloud directory path, organized by system name."""
    if system_id is None:
        return '/dashboard/dashboard/'
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute('SELECT service_name FROM systems WHERE id=?', (system_id,)).fetchone()
    conn.close()
    name = row['service_name'] if row else str(system_id)
    return f'/dashboard/{name}/'


@webdav_bp.route('/api/webdav/config', methods=['GET'])
def get_webdav_config():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute('SELECT * FROM webdav_config LIMIT 1').fetchone()
    conn.close()
    if not row:
        return jsonify({'configured': False})
    return jsonify({'configured': True, 'webdav_url': row['webdav_url'], 'username': row['username'], 'password': ''})


@webdav_bp.route('/api/webdav/config', methods=['POST'])
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


@webdav_bp.route('/api/webdav/check', methods=['POST'])
def check_webdav():
    try:
        client = _get_webdav_client()
        client.list()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


@webdav_bp.route('/api/webdav/list')
def list_webdav_files():
    """List cloud files for a specific system directory."""
    system_id = request.args.get('system_id', type=int)
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


@webdav_bp.route('/api/webdav/upload', methods=['POST'])
def upload_to_webdav():
    d = request.json
    local_path = d.get('local_path')
    remote_path = d.get('remote_path')
    system_id = d.get('system_id')
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


@webdav_bp.route('/api/webdav/download', methods=['POST'])
def download_from_webdav():
    """Download backup from cloud, optionally restore after download."""
    d = request.json
    remote_path = d.get('remote_path')
    system_id = d.get('system_id')
    do_restore = d.get('restore', False)
    if not remote_path:
        return jsonify({'ok': False, 'error': '缺少 remote_path'}), 400

    # Determine local backup directory and target database
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
            if service_name:
                _systemctl(['stop', service_name])
                time.sleep(1)
            pre_name = 'pre_restore_' + _backup_filename()
            pre_path = os.path.join(backup_dir, pre_name)
            shutil.copy2(target_db, pre_path)
            shutil.copy2(local_path, target_db)
            if service_name:
                _systemctl(['start', service_name])
            return jsonify({'ok': True, 'restored': True, 'local_path': local_path})

        return jsonify({'ok': True, 'local_path': local_path})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
