"""WSL performance monitoring routes and background sampler."""
import sqlite3
import threading
import atexit
from datetime import datetime, timedelta, timezone

import psutil
from flask import Blueprint, request, jsonify

from config import CFG
from db import DB_PATH

wsl_bp = Blueprint('wsl', __name__)

METRICS_INTERVAL = CFG['metrics']['interval']
METRICS_RETENTION_DAYS = CFG['metrics']['retention_days']
METRICS_MAX_POINTS = CFG['metrics']['max_points']
_sampler_stop = threading.Event()


def _record_boot_event():
    """Detect and record boot event on startup."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    boot_time = datetime.fromtimestamp(psutil.boot_time(), tz=timezone.utc)
    boot_str = boot_time.strftime('%Y-%m-%dT%H:%M:%SZ')
    c.execute('SELECT id FROM wsl_events WHERE event_type=? AND timestamp=?',
              ('boot', boot_str))
    if not c.fetchone():
        c.execute('INSERT INTO wsl_events (event_type, timestamp, detail) VALUES (?,?,?)',
                  ('boot', boot_str, 'uptime detection'))
        c.execute('SELECT timestamp FROM wsl_events WHERE event_type IN (?,?) ORDER BY timestamp DESC LIMIT 1',
                  ('boot', 'shutdown'))
        prev = c.fetchone()
        if prev:
            last_ts = datetime.fromisoformat(prev[0].replace('Z', '+00:00'))
            if boot_time - last_ts > timedelta(hours=1):
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
            (ts, cpu, round(mem.used / (1024 ** 3), 2), round(mem.total / (1024 ** 3), 1),
             round(mem.percent, 1), round(disk.used / (1024 ** 3), 2), round(disk.total / (1024 ** 3), 1),
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
    _sample_metrics()
    while not _sampler_stop.wait(METRICS_INTERVAL):
        _sample_metrics()


def start_metrics_sampler():
    """Start background metrics sampler and record boot event."""
    _record_boot_event()
    atexit.register(_record_shutdown_event)
    t = threading.Thread(target=_sampler_loop, daemon=True)
    t.start()


@wsl_bp.route('/api/wsl/metrics')
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
            'total': round(mem.total / (1024 ** 3), 1),
            'used': round(mem.used / (1024 ** 3), 1),
            'percent': mem.percent
        },
        'disk': {
            'total': round(disk.total / (1024 ** 3), 1),
            'used': round(disk.used / (1024 ** 3), 1),
            'percent': round(disk.percent, 1)
        },
        'uptime': uptime_str
    })


@wsl_bp.route('/api/wsl/metrics/history')
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

    raw = [dict(r) for r in rows]
    if len(raw) > METRICS_MAX_POINTS:
        step = len(raw) / METRICS_MAX_POINTS
        metrics = [raw[int(i * step)] for i in range(METRICS_MAX_POINTS)]
    else:
        metrics = raw

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


@wsl_bp.route('/api/wsl/events')
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
