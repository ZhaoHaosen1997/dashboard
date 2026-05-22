"""WSL performance monitoring routes and background sampler."""
import os
import sqlite3
import subprocess
import threading
import time
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

# IO rate tracking (need two samples to calculate rate)
_last_io = {'ts': 0, 'disk_read': 0, 'disk_write': 0, 'net_sent': 0, 'net_recv': 0}
_io_lock = threading.Lock()

# GPU availability (lazy detect, cache result; reset on failure after N tries)
_gpu_available = None
_gpu_fail_count = 0
_GPU_MAX_FAILS = 10  # allow re-detection after 10 consecutive failures


NVIDIA_SMI_PATHS = [
    'nvidia-smi',
    '/usr/lib/wsl/lib/nvidia-smi',
    '/usr/bin/nvidia-smi',
    '/usr/local/cuda/bin/nvidia-smi',
]
_nvidia_smi = None  # resolved path


def _find_nvidia_smi():
    """Find nvidia-smi binary. Returns path or None."""
    global _nvidia_smi
    if _nvidia_smi is not None:
        return _nvidia_smi if _nvidia_smi else None
    for p in NVIDIA_SMI_PATHS:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            _nvidia_smi = p
            return p
    # Check via shutil
    import shutil
    found = shutil.which('nvidia-smi')
    _nvidia_smi = found or ''
    return found


def _get_gpu():
    """Query GPU info via nvidia-smi. Returns dict or None."""
    global _gpu_available, _gpu_fail_count
    if _gpu_available is False:
        _gpu_fail_count += 1
        if _gpu_fail_count < _GPU_MAX_FAILS:
            return None
        # Reset after enough failures — allow re-detection
        _gpu_available = None
        _gpu_fail_count = 0
    smi = _find_nvidia_smi()
    if not smi:
        _gpu_available = False
        return None
    try:
        out = subprocess.check_output(
            [smi, '--query-gpu=name,temperature.gpu,utilization.gpu,'
             'memory.used,memory.total,power.draw,power.limit',
             '--format=csv,noheader,nounits'],
            timeout=5, encoding='utf-8', errors='replace'
        ).strip()
        _gpu_available = True
        _gpu_fail_count = 0
        parts = [x.strip() for x in out.split(',')]
        return {
            'name': parts[0],
            'temperature': float(parts[1]),
            'utilization': float(parts[2]),
            'memory_used': float(parts[3]),
            'memory_total': float(parts[4]),
            'power_draw': float(parts[5]),
            'power_limit': float(parts[6])
        }
    except Exception:
        _gpu_available = False
        return None


def _get_io_rates():
    """Calculate disk and network IO rates from two samples."""
    global _last_io
    now = time.time()
    disk = psutil.disk_io_counters()
    net = psutil.net_io_counters()
    if not disk or not net:
        return {'disk_read_rate': 0, 'disk_write_rate': 0,
                'net_sent_rate': 0, 'net_recv_rate': 0}

    with _io_lock:
        elapsed = now - _last_io['ts']
        if elapsed < 0.5 or _last_io['ts'] == 0:
            # First sample or too fast, just record and return zeros
            _last_io = {
                'ts': now,
                'disk_read': disk.read_bytes, 'disk_write': disk.write_bytes,
                'net_sent': net.bytes_sent, 'net_recv': net.bytes_recv
            }
            return {'disk_read_rate': 0, 'disk_write_rate': 0,
                    'net_sent_rate': 0, 'net_recv_rate': 0}

        result = {
            'disk_read_rate': round((disk.read_bytes - _last_io['disk_read']) / elapsed / (1024 ** 2), 2),
            'disk_write_rate': round((disk.write_bytes - _last_io['disk_write']) / elapsed / (1024 ** 2), 2),
            'net_sent_rate': round((net.bytes_sent - _last_io['net_sent']) / elapsed / (1024 ** 2), 2),
            'net_recv_rate': round((net.bytes_recv - _last_io['net_recv']) / elapsed / (1024 ** 2), 2),
        }
        _last_io = {
            'ts': now,
            'disk_read': disk.read_bytes, 'disk_write': disk.write_bytes,
            'net_sent': net.bytes_sent, 'net_recv': net.bytes_recv
        }
    return result


def _get_top_processes(n=20):
    """Get top N processes by CPU usage, with rich info."""
    procs = []
    now = time.time()
    for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_info', 'memory_percent', 'num_threads', 'status', 'create_time']):
        try:
            info = p.info
            if info['cpu_percent'] is None:
                info['cpu_percent'] = 0
            # Calculate runtime
            runtime = ''
            if info.get('create_time'):
                secs = int(now - info['create_time'])
                h, rem = divmod(secs, 3600)
                m, s = divmod(rem, 60)
                if h > 0:
                    runtime = f'{h}h{m}m'
                elif m > 0:
                    runtime = f'{m}m{s}s'
                else:
                    runtime = f'{s}s'
            procs.append({
                'pid': info['pid'],
                'name': info['name'] or 'unknown',
                'cpu': round(info['cpu_percent'], 1),
                'mem_mb': round((info['memory_info'].rss or 0) / (1024 ** 2), 1) if info.get('memory_info') else 0,
                'mem_pct': round(info.get('memory_percent') or 0, 1),
                'threads': info.get('num_threads') or 0,
                'status': (info.get('status') or '?').lower(),
                'runtime': runtime
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    procs.sort(key=lambda x: x['cpu'], reverse=True)
    return procs[:n]


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
        gpu = _get_gpu()
        io = _get_io_rates()
        try:
            load1, load5, load15 = os.getloadavg()
        except (OSError, ValueError):
            load1 = load5 = load15 = 0
        ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            '''INSERT INTO wsl_metrics (timestamp, cpu_percent, mem_used, mem_total, mem_percent,
               disk_used, disk_total, disk_percent,
               gpu_util, gpu_mem_used, gpu_temp, gpu_power,
               disk_read_rate, disk_write_rate, net_sent_rate, net_recv_rate,
               load1, load5, load15)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (ts, cpu, round(mem.used / (1024 ** 3), 2), round(mem.total / (1024 ** 3), 1),
             round(mem.percent, 1), round(disk.used / (1024 ** 3), 2), round(disk.total / (1024 ** 3), 1),
             round(disk.percent, 1),
             gpu['utilization'] if gpu else None,
             gpu['memory_used'] if gpu else None,
             gpu['temperature'] if gpu else None,
             gpu['power_draw'] if gpu else None,
             io['disk_read_rate'], io['disk_write_rate'],
             io['net_sent_rate'], io['net_recv_rate'],
             round(load1, 2), round(load5, 2), round(load15, 2)))
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
    cpu_percent = psutil.cpu_percent(interval=0)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    swap = psutil.swap_memory()
    gpu = _get_gpu()
    io = _get_io_rates()
    try:
        load_avg = list(os.getloadavg())
        load_avg = [round(l, 2) for l in load_avg]
    except (OSError, ValueError):
        load_avg = [0, 0, 0]
    top_procs = _get_top_processes(20)

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
            'percent': round(mem.percent, 1),
            'cached': round((getattr(mem, 'cached', 0) or 0) / (1024 ** 3), 1),
            'available': round(mem.available / (1024 ** 3), 1),
            'swap_percent': round(swap.percent, 1)
        },
        'disk': {
            'total': round(disk.total / (1024 ** 3), 1),
            'used': round(disk.used / (1024 ** 3), 1),
            'percent': round(disk.percent, 1)
        },
        'gpu': gpu,
        'disk_io': {'disk_read_rate': io['disk_read_rate'], 'disk_write_rate': io['disk_write_rate']},
        'net_io': {'net_sent_rate': io['net_sent_rate'], 'net_recv_rate': io['net_recv_rate']},
        'load_avg': load_avg,
        'top_processes': top_procs,
        'uptime': uptime_str
    })


@wsl_bp.route('/api/wsl/metrics/history')
def wsl_metrics_history():
    """Return historical metrics with downsampling and events."""
    hours = request.args.get('hours', 24, type=int)
    metric = request.args.get('metric', '')  # optional: filter by specific metric field
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime('%Y-%m-%dT%H:%M:%SZ')

    # Determine which columns to select
    if metric in ('cpu_percent', 'mem_percent', 'disk_percent', 'gpu_util', 'gpu_mem_used',
                   'gpu_temp', 'gpu_power', 'load1'):
        col = metric
    else:
        col = 'cpu_percent'  # default

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        f'SELECT timestamp, {col} FROM wsl_metrics WHERE timestamp >= ? AND {col} IS NOT NULL ORDER BY timestamp',
        (cutoff,)).fetchall()
    conn.close()

    raw = [{'timestamp': r['timestamp'], 'value': r[col]} for r in rows]
    if len(raw) > METRICS_MAX_POINTS:
        step = len(raw) / METRICS_MAX_POINTS
        data = [raw[int(i * step)] for i in range(METRICS_MAX_POINTS)]
    else:
        data = raw

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    events = conn.execute(
        'SELECT event_type, timestamp FROM wsl_events WHERE timestamp >= ? ORDER BY timestamp',
        (cutoff,)).fetchall()
    conn.close()

    return jsonify({
        'metric': metric,
        'data': data,
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
