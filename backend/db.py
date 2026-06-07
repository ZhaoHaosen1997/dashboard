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
            disk_used REAL, disk_total REAL, disk_percent REAL,
            gpu_util REAL, gpu_mem_used REAL, gpu_temp REAL, gpu_power REAL,
            disk_read_rate REAL, disk_write_rate REAL,
            net_sent_rate REAL, net_recv_rate REAL,
            load1 REAL, load5 REAL, load15 REAL)''')
        c.execute('CREATE INDEX idx_wsl_metrics_ts ON wsl_metrics(timestamp)')
    else:
        # Migrate: add new columns for v0.5 monitoring
        c.execute("PRAGMA table_info(wsl_metrics)")
        existing = [col[1] for col in c.fetchall()]
        for field, dtype in [('gpu_util', 'REAL'), ('gpu_mem_used', 'REAL'),
                             ('gpu_temp', 'REAL'), ('gpu_power', 'REAL'),
                             ('disk_read_rate', 'REAL'), ('disk_write_rate', 'REAL'),
                             ('net_sent_rate', 'REAL'), ('net_recv_rate', 'REAL'),
                             ('load1', 'REAL'), ('load5', 'REAL'), ('load15', 'REAL')]:
            if field not in existing:
                c.execute(f'ALTER TABLE wsl_metrics ADD COLUMN {field} {dtype}')

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

    # net_traffic table (from vnstat, hourly aggregates)
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='net_traffic'")
    if not c.fetchone():
        c.execute('''CREATE TABLE net_traffic (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            interface TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            rx_bytes INTEGER DEFAULT 0,
            tx_bytes INTEGER DEFAULT 0)''')
        c.execute('CREATE INDEX idx_net_traffic_ts ON net_traffic(timestamp)')
        c.execute('CREATE INDEX idx_net_traffic_iface ON net_traffic(interface)')

    # net_process table (from nethogs, per-process traffic samples)
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='net_process'")
    if not c.fetchone():
        c.execute('''CREATE TABLE net_process (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            pid INTEGER,
            process_name TEXT NOT NULL,
            sent_bytes INTEGER DEFAULT 0,
            recv_bytes INTEGER DEFAULT 0)''')
        c.execute('CREATE INDEX idx_net_process_ts ON net_process(timestamp)')
        c.execute('CREATE INDEX idx_net_process_name ON net_process(process_name)')

    # net_conn table (from ss, connection snapshots)
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='net_conn'")
    if not c.fetchone():
        c.execute('''CREATE TABLE net_conn (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            local_ip TEXT, local_port INTEGER,
            remote_ip TEXT NOT NULL, remote_port INTEGER,
            proto TEXT, pid INTEGER,
            process_name TEXT)''')
        c.execute('CREATE INDEX idx_net_conn_ts ON net_conn(timestamp)')
        c.execute('CREATE INDEX idx_net_conn_rip ON net_conn(remote_ip)')

    # net_alert table (anomaly alerts)
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='net_alert'")
    if not c.fetchone():
        c.execute('''CREATE TABLE net_alert (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            severity TEXT DEFAULT "info",
            remote_ip TEXT, port INTEGER,
            process_name TEXT,
            detail TEXT,
            acknowledged INTEGER DEFAULT 0)''')
        c.execute('CREATE INDEX idx_net_alert_ts ON net_alert(timestamp)')

    # net_whitelist table (IP whitelist for alert suppression)
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='net_whitelist'")
    if not c.fetchone():
        c.execute('''CREATE TABLE net_whitelist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cidr TEXT NOT NULL UNIQUE,
            note TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        # insert default whitelist entries
        defaults = [
            ('192.163.20.0/24', '局域网'),
            ('100.64.0.0/10', 'Tailscale'),
            ('127.0.0.0/8', '本机回环'),
        ]
        c.executemany('INSERT INTO net_whitelist (cidr, note) VALUES (?,?)', defaults)

    # gpu_lock_log table (lock/unlock event history)
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='gpu_lock_log'")
    if not c.fetchone():
        c.execute('''CREATE TABLE gpu_lock_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            action TEXT NOT NULL,
            who TEXT DEFAULT '',
            source TEXT DEFAULT 'manual')''')
        c.execute('CREATE INDEX idx_gpu_log_ts ON gpu_lock_log(timestamp)')

    conn.commit()
    conn.close()


def init_db(app):
    """Initialize database: run migrations or create with defaults."""
    is_new = not os.path.exists(DB_PATH)
    if is_new:
        # Bootstrap systems table and default rows first
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
    # Always run migrate_db to ensure all tables exist (covers new DB and upgrades)
    migrate_db()
