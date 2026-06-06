"""GPU lock management routes + auto lock/unlock background thread."""
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify

from db import DB_PATH

gpu_bp = Blueprint('gpu', __name__)

LOCK_SCRIPT = '/home/zhaohaosen/scripts/gpu_lock.sh'

# Auto lock/unlock config
AUTO_CHECK_INTERVAL = 15       # seconds between GPU idle checks
IDLE_THRESHOLD = 5             # GPU util below this % is "idle"
IDLE_DURATION = 60             # seconds of idle before auto-lock
BUSY_DURATION = 30             # seconds of busy before auto-unlock (when locked by auto)

_auto_stop = threading.Event()
_auto_state = {
    'enabled': True,
    'idle_since': None,        # timestamp when GPU first went idle
    'busy_since': None,        # timestamp when GPU first went busy (locked by auto)
    'last_util': 0,
    'interval': AUTO_CHECK_INTERVAL,
    'idle_threshold': IDLE_THRESHOLD,
    'idle_duration': IDLE_DURATION,
    'busy_duration': BUSY_DURATION,
}


def _run_script(*args):
    """Run gpu_lock.sh with given args, return (stdout, returncode)."""
    try:
        r = subprocess.run(
            [LOCK_SCRIPT] + list(args),
            capture_output=True, text=True, timeout=10
        )
        return r.stdout.strip(), r.returncode
    except FileNotFoundError:
        return None, -1
    except subprocess.TimeoutExpired:
        return None, -2


def _parse_status(text):
    """Parse gpu_lock.sh status output into locked/who."""
    if text is None:
        return {'locked': False, 'who': None, 'note': 'GPU lock script not available'}
    if text.startswith('🔒'):
        who = text.replace('🔒 GPU 被 ', '').replace(' 占用', '').strip()
        return {'locked': True, 'who': who}
    return {'locked': False, 'who': None}


def _get_gpu_util():
    """Quick GPU utilization from nvidia-smi. Returns float or None."""
    try:
        r = subprocess.run(
            ['nvidia-smi', '--query-gpu=utilization.gpu',
             '--format=csv,noheader,nounits'],
            capture_output=True, text=True, timeout=5
        )
        return float(r.stdout.strip())
    except Exception:
        return None


def _log_event(action, who, source='manual'):
    """Record a lock/unlock event in gpu_lock_log."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            'INSERT INTO gpu_lock_log (timestamp, action, who, source) VALUES (?,?,?,?)',
            (datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), action, who, source)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _get_logs(limit=10):
    """Fetch recent lock/unlock events."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            'SELECT * FROM gpu_lock_log ORDER BY timestamp DESC LIMIT ?', (limit,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


_lock_thread_started = False


# ── API routes ────────────────────────────────────────────────────

@gpu_bp.route('/api/gpu/lock', methods=['GET'])
def get_lock():
    """查看 GPU 锁状态"""
    out, _ = _run_script('status')
    info = _parse_status(out)
    info['auto'] = _auto_state
    return jsonify(info)


@gpu_bp.route('/api/gpu/lock', methods=['PUT'])
def acquire_lock():
    """加锁"""
    data = request.get_json(silent=True) or {}
    who = data.get('who', 'comfyui')
    out, rc = _run_script('lock', who)
    if rc == -1:
        return jsonify({'ok': False, 'message': 'GPU lock script not available'}), 500
    _log_event('lock', who, 'manual')
    return jsonify({'ok': True, 'message': out})


@gpu_bp.route('/api/gpu/lock', methods=['DELETE'])
def release_lock():
    """解锁"""
    # Get who currently holds the lock for logging
    status_out, _ = _run_script('status')
    info = _parse_status(status_out)
    who = info.get('who', 'unknown')
    out, rc = _run_script('unlock')
    if rc == -1:
        return jsonify({'ok': False, 'message': 'GPU lock script not available'}), 500
    _log_event('unlock', who, 'manual')
    return jsonify({'ok': True, 'message': out})


@gpu_bp.route('/api/gpu/lock/check')
def check_lock():
    """快速检测 GPU 是否被占用（HTTP 状态码驱动）"""
    out, rc = _run_script('check')
    if rc == -1:
        return jsonify({'locked': False, 'note': 'GPU lock script not available'})
    if rc == 0:
        return jsonify({'locked': False})
    status_out, _ = _run_script('status')
    info = _parse_status(status_out)
    return jsonify({'locked': True, 'who': info.get('who')}), 409


@gpu_bp.route('/api/gpu/lock/auto', methods=['GET'])
def get_auto_config():
    """获取自动加锁解锁配置和状态"""
    return jsonify(_auto_state)


@gpu_bp.route('/api/gpu/lock/auto', methods=['PUT'])
def update_auto_config():
    """更新自动加锁解锁配置"""
    data = request.get_json(silent=True) or {}
    if 'enabled' in data:
        _auto_state['enabled'] = bool(data['enabled'])
    if 'interval' in data:
        _auto_state['interval'] = int(data['interval'])
    if 'idle_threshold' in data:
        _auto_state['idle_threshold'] = int(data['idle_threshold'])
    if 'idle_duration' in data:
        _auto_state['idle_duration'] = int(data['idle_duration'])
    if 'busy_duration' in data:
        _auto_state['busy_duration'] = int(data['busy_duration'])
    return jsonify({'ok': True, 'config': _auto_state})


@gpu_bp.route('/api/gpu/lock/log')
def get_lock_log():
    """获取最近加锁/解锁记录"""
    limit = request.args.get('limit', 10, type=int)
    return jsonify(_get_logs(limit))


# ── Auto lock/unlock thread ────────────────────────────────────────

def _auto_lock_loop():
    """Background thread: periodically check GPU idle and auto lock/unlock."""
    while not _auto_stop.is_set():
        _auto_stop.wait(_auto_state['interval'])
        if _auto_stop.is_set():
            break

        if not _auto_state['enabled']:
            continue

        util = _get_gpu_util()
        if util is None:
            continue
        _auto_state['last_util'] = util

        now = time.time()
        threshold = _auto_state['idle_threshold']
        is_idle = util < threshold

        # Check current lock state
        out, rc = _run_script('check')
        locked = (rc == 1)

        if not locked and is_idle:
            # GPU is idle and unlocked — track idle duration
            if _auto_state['idle_since'] is None:
                _auto_state['idle_since'] = now
                _auto_state['busy_since'] = None
            elif now - _auto_state['idle_since'] >= _auto_state['idle_duration']:
                # Idle long enough — auto lock
                _run_script('lock', 'auto-idle')
                _log_event('lock', 'auto-idle', 'auto')
                _auto_state['idle_since'] = None
        elif not locked and not is_idle:
            # GPU is busy and unlocked — reset tracking
            _auto_state['idle_since'] = None
            _auto_state['busy_since'] = None
        elif locked:
            # GPU is locked — check who
            status_out, _ = _run_script('status')
            info = _parse_status(status_out)

            if info.get('who') == 'auto-idle':
                if is_idle:
                    _auto_state['busy_since'] = None
                else:
                    # GPU became busy while auto-locked — track for unlock
                    if _auto_state['busy_since'] is None:
                        _auto_state['busy_since'] = now
                    elif now - _auto_state['busy_since'] >= _auto_state['busy_duration']:
                        # Busy long enough — auto unlock (someone needs it)
                        _run_script('unlock')
                        _log_event('unlock', 'auto-idle', 'auto')
                        _auto_state['busy_since'] = None

            _auto_state['idle_since'] = None


def start_gpu_auto_lock():
    """Start the auto lock/unlock background thread."""
    global _lock_thread_started
    if _lock_thread_started:
        return
    _lock_thread_started = True
    t = threading.Thread(target=_auto_lock_loop, daemon=True, name='gpu-auto-lock')
    t.start()
