"""Resource threshold alerter.

Tracks consecutive threshold violations and dispatches notifications via:
  - WeChat Work (企业微信) group robot webhook
  - In-memory alert state (polled by frontend for visual effects)

All configuration is read from config.yml (alerts / notify sections).
Nothing is hardcoded.
"""
import json
import logging
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

import psutil
import requests

from config import CFG
from db import DB_PATH

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level state (thread-safe via _lock)
# ---------------------------------------------------------------------------
_lock = threading.Lock()

# hit_count[metric] = int  — consecutive samples above threshold
_hit_count: dict[str, int] = {}

# last_notify_time[metric] = datetime  — when we last sent a notification
_last_notify: dict[str, datetime] = {}

# active_alerts[metric] = bool  — currently in alert state (for frontend polling)
_active_alerts: dict[str, bool] = {}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cfg_alerts():
    return CFG.get('alerts', {})

def _cfg_notify():
    return CFG.get('notify', {})

def _hostname():
    import socket
    return socket.gethostname()

def _metric_label(metric: str) -> str:
    return {
        'cpu':    'CPU 使用率',
        'memory': '内存使用率',
        'disk':   '磁盘使用率',
        'gpu':    'GPU 使用率',
    }.get(metric, metric)

def _get_top_processes(n: int = 8) -> list:
    """Snapshot top N processes by CPU% at the moment of alert.

    Returns a list of dicts with: pid, name, cpu, mem_mb, mem_pct.
    Safe to call from any thread; psutil errors are suppressed.
    """
    try:
        procs = []
        for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_info', 'memory_percent']):
            try:
                info = p.info
                cpu = info.get('cpu_percent') or 0.0
                mem_info = info.get('memory_info')
                mem_mb = round(mem_info.rss / 1024 / 1024, 1) if mem_info else 0.0
                mem_pct = round(info.get('memory_percent') or 0.0, 1)
                procs.append({
                    'pid':     info['pid'],
                    'name':    info.get('name', '?'),
                    'cpu':     round(cpu, 1),
                    'mem_mb':  mem_mb,
                    'mem_pct': mem_pct,
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        # Sort by CPU% descending, break ties by memory
        procs.sort(key=lambda x: (-x['cpu'], -x['mem_mb']))
        return procs[:n]
    except Exception as e:
        logger.warning('_get_top_processes failed: %s', e)
        return []


def _fmt_top_processes_text(procs: list) -> str:
    """Format top processes as a compact text block for Wecom notification."""
    if not procs:
        return ''
    lines = ['Top Processes:']
    for p in procs:
        lines.append(f"  {p['name']}({p['pid']})  CPU {p['cpu']}%  Mem {p['mem_mb']}MB")
    return '\n'.join(lines)


def _record_alert(metric: str, value: float, threshold: float, top_procs: list | None = None):
    """Persist alert record to database."""
    try:
        ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        procs_json = json.dumps(top_procs, ensure_ascii=False) if top_procs else None
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            'INSERT INTO resource_alerts (timestamp, metric, value, threshold, top_processes) VALUES (?,?,?,?,?)',
            (ts, metric, round(value, 1), threshold, procs_json)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning('Failed to record alert: %s', e)

def _send_wecom(metric: str, value: float, threshold: float, top_procs: list | None = None):
    """Send WeChat Work group robot message."""
    wcfg = _cfg_notify().get('wecom_webhook', {})
    if not wcfg.get('enabled') or not wcfg.get('url', '').strip():
        return

    url = wcfg['url'].strip()
    host = _hostname()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    title_tpl = wcfg.get('title_template', '[Dashboard] {host} 资源告警')
    body_tpl = wcfg.get('body_template',
                        '指标: {metric}\n当前值: {value}%\n阈值: {threshold}%\n时间: {time}')

    title = title_tpl.format(host=host, metric=_metric_label(metric),
                             value=round(value, 1), threshold=threshold)
    body = body_tpl.format(host=host, metric=_metric_label(metric),
                           value=round(value, 1), threshold=threshold, time=now)

    # Append top processes block if available
    procs_text = _fmt_top_processes_text(top_procs) if top_procs else ''
    if procs_text:
        body = body + '\n\n' + procs_text

    payload = {
        'msgtype': 'text',
        'text': {
            'content': f'{title}\n{body}'
        }
    }
    try:
        resp = requests.post(url, json=payload, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('errcode') == 0:
                logger.info('WecomBot alert sent: %s=%.1f%%', metric, value)
            else:
                logger.warning('WecomBot error: %s', data)
        else:
            logger.warning('WecomBot HTTP %s', resp.status_code)
    except Exception as e:
        logger.warning('WecomBot send failed: %s', e)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_and_alert(metrics: dict):
    """Called after each metrics sample. metrics keys: cpu, memory, disk, gpu.

    metrics example:
        {'cpu': 23.5, 'memory': 61.2, 'disk': 45.0, 'gpu': None}
    GPU may be None when no GPU is present — skip silently.
    """
    acfg = _cfg_alerts()
    if not acfg.get('enabled', True):
        return

    thresholds: dict = acfg.get('thresholds', {})
    consecutive_hits: int = int(acfg.get('consecutive_hits', 3))
    silence_minutes: int = int(acfg.get('silence_minutes', 60))

    now = datetime.now(timezone.utc)

    with _lock:
        for metric, threshold in thresholds.items():
            value = metrics.get(metric)
            if value is None:
                # e.g. gpu on a machine without GPU — reset state and skip
                _hit_count[metric] = 0
                _active_alerts[metric] = False
                continue

            threshold = float(threshold)
            above = value > threshold

            if above:
                _hit_count[metric] = _hit_count.get(metric, 0) + 1
            else:
                _hit_count[metric] = 0
                _active_alerts[metric] = False
                continue

            # Mark as active alert for frontend regardless of notification silence
            _active_alerts[metric] = (_hit_count[metric] >= consecutive_hits)

            if _hit_count[metric] < consecutive_hits:
                continue  # not enough consecutive hits yet

            # Check silence period
            last = _last_notify.get(metric)
            if last and (now - last) < timedelta(minutes=silence_minutes):
                continue  # still in silence window

            # Snapshot top processes at the moment of alert
            top_procs = _get_top_processes(8)

            # Fire notification
            _last_notify[metric] = now
            _record_alert(metric, value, threshold, top_procs)
            _send_wecom(metric, value, threshold, top_procs)
            logger.info('Alert fired: %s=%.1f%% (threshold=%.0f%%)', metric, value, threshold)


def get_alert_status() -> dict:
    """Return current alert state for all monitored metrics.

    Returns dict like:
        {
          'cpu':    {'active': False, 'hit_count': 0},
          'memory': {'active': True,  'hit_count': 4},
          ...
        }
    """
    acfg = _cfg_alerts()
    thresholds: dict = acfg.get('thresholds', {})
    result = {}
    with _lock:
        for metric in thresholds:
            result[metric] = {
                'active': _active_alerts.get(metric, False),
                'hit_count': _hit_count.get(metric, 0),
                'threshold': float(thresholds[metric]),
            }
    return result


def get_alert_history(days: int = 7, limit: int = 200) -> list:
    """Return recent alert records from database."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%SZ')
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            'SELECT id, timestamp, metric, value, threshold, notified, top_processes '
            'FROM resource_alerts WHERE timestamp >= ? ORDER BY timestamp DESC LIMIT ?',
            (cutoff, limit)
        ).fetchall()
        conn.close()
        result = []
        for r in rows:
            d = dict(r)
            # Parse top_processes JSON back to list
            if d.get('top_processes'):
                try:
                    d['top_processes'] = json.loads(d['top_processes'])
                except Exception:
                    d['top_processes'] = []
            else:
                d['top_processes'] = []
            result.append(d)
        return result
    except Exception as e:
        logger.warning('get_alert_history failed: %s', e)
        return []
