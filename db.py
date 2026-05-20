"""Database layer - connection management, initialization, migrations."""
import os
import sqlite3
from flask import g

from config import CFG

DB_PATH = CFG['database']['abs_path']


def get_db():
    """Get per-request database connection via Flask g object."""
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(e):
    """Teardown: close database connection."""
    db = g.pop('db', None)
    if db:
        db.close()


def migrate_db():
    """Incremental migration: add new columns and tables as needed."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # systems table migrations
    c.execute("PRAGMA table_info(systems)")
    columns = [col[1] for col in c.fetchall()]
    if 'service_name' not in columns:
        c.execute('ALTER TABLE systems ADD COLUMN service_name TEXT')
    for field, dtype in [('db_path', 'TEXT'), ('backup_enabled', 'INTEGER DEFAULT 0'),
                         ('backup_interval', "TEXT DEFAULT 'daily'"),
                         ('backup_keep', 'INTEGER DEFAULT 3'), ('last_backup', 'TEXT')]:
        if field not in columns:
            c.execute(f'ALTER TABLE systems ADD COLUMN {field} {dtype}')

    # wsl_metrics table
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='wsl_metrics'")
    if not c.fetchone():
        c.execute('''CREATE TABLE wsl_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            cpu_percent REAL,
            mem_used REAL, mem_total REAL, mem_percent REAL,
            disk_used REAL, disk_total REAL, disk_percent REAL)''')
        c.execute('CREATE INDEX idx_wsl_metrics_ts ON wsl_metrics(timestamp)')

    # wsl_events table
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='wsl_events'")
    if not c.fetchone():
        c.execute('''CREATE TABLE wsl_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            detail TEXT)''')
        c.execute('CREATE INDEX idx_wsl_events_ts ON wsl_events(timestamp)')

    # webdav_config table
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='webdav_config'")
    if not c.fetchone():
        c.execute('''CREATE TABLE webdav_config (
            id INTEGER PRIMARY KEY, webdav_url TEXT, username TEXT,
            password_encrypted TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    # backup_records table
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='backup_records'")
    if not c.fetchone():
        c.execute('''CREATE TABLE backup_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT, system_id INTEGER,
            backup_file TEXT NOT NULL, backup_path TEXT NOT NULL,
            file_size INTEGER, backup_type TEXT DEFAULT 'manual',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    conn.commit()
    conn.close()


def init_db(app):
    """Initialize database: run migrations or create with defaults."""
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
    conn.commit()
    conn.close()
