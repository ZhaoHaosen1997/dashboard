"""Utility functions - encryption, system control, backup helpers."""
import os
import subprocess
import time
import shutil
import sqlite3
from datetime import datetime
from cryptography.fernet import Fernet

from config import CFG
from db import DB_PATH

KEY_DIR = CFG['encryption']['key_dir']
KEY_FILE = CFG['encryption']['key_file']
BACKUP_BASE = CFG['backup']['base_dir']


# --- Encryption ---

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


# --- System control ---

def _systemctl(args, timeout=None):
    if timeout is None:
        timeout = CFG['timeout']['systemctl']
    return subprocess.run(
        ['sudo', 'systemctl'] + args,
        capture_output=True, text=True, timeout=timeout, encoding='utf-8', errors='replace'
    )


def _journalctl(args, timeout=None):
    if timeout is None:
        timeout = CFG['timeout']['journalctl']
    return subprocess.run(
        ['sudo', 'journalctl'] + args,
        capture_output=True, text=True, timeout=timeout, encoding='utf-8', errors='replace'
    )


# --- Backup helpers ---

def _get_backup_dir(system_id=None):
    """Get backup directory path. system_id=None means Dashboard itself."""
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
    """Execute a single backup."""
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
    keep = row['backup_keep'] if row else CFG['backup']['default_keep']
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


def restore_backup(system_id=None, backup_path=None):
    """Restore database from a backup file."""
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


# --- Startup backup check ---

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
            interval_days = CFG['backup']['interval_days'].get(s['backup_interval'] if s else CFG['backup']['default_interval'], 1)
            if s and s['last_backup']:
                if (datetime.now() - datetime.fromisoformat(s['last_backup'])).days < interval_days:
                    continue
            perform_backup(row['id'], backup_type='auto')
        except Exception:
            pass


def _startup_backup_thread():
    """Background startup backup check with debounce."""
    stamp_file = os.path.join(KEY_DIR, '.last_backup_check')
    debounce = CFG['backup']['check_debounce']
    try:
        with open(stamp_file, 'r') as f:
            if time.time() - float(f.read().strip()) < debounce:
                return
    except (FileNotFoundError, ValueError):
        pass
    with open(stamp_file, 'w') as f:
        f.write(str(time.time()))
    _startup_backup_check()
