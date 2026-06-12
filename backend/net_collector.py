"""Network traffic collector - background threads for vnstat, nethogs, ss."""
import ipaddress
import json
import logging
import os
import re
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timezone, timedelta

from config import CFG
from db import DB_PATH

logger = logging.getLogger(__name__)

# Monitoring interfaces - read from config.yml (network.monitor_ifaces)
MONITOR_IFACES = CFG.get('network', {}).get('monitor_ifaces', ['eth0'])

# Collection intervals
VSTAT_INTERVAL = 3600       # 1 hour
NETHOGS_INTERVAL = 60       # 1 minute snapshot
SS_INTERVAL = 60            # 1 minute snapshot
CLEANUP_INTERVAL = 3600 * 6  # every 6 hours

# Retention (days)
RETENTION_TRAFFIC = 90
RETENTION_PROCESS = 30
RETENTION_CONN = 7
RETENTION_ALERT = 90

_stop = threading.Event()


def _get_conn():
    """Get a dedicated SQLite connection for collector threads."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ── vnstat collector ──────────────────────────────────────────────

def _collect_vnstat():
    """Query vnstat JSON and insert hourly traffic into net_traffic."""
    conn = _get_conn()
    try:
        result = subprocess.run(
            ['vnstat', '--json', 'h', '50'],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return
        data = json.loads(result.stdout)
        now_ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:00:00Z')

        for iface in data.get('interfaces', []):
            name = iface['name']
            if name not in MONITOR_IFACES:
                continue
            for hour_entry in iface.get('traffic', {}).get('hour', []):
                ts_str = f"{hour_entry['date']['year']:04d}-"
                ts_str += f"{hour_entry['date']['month']:02d}-"
                ts_str += f"{hour_entry['date']['day']:02d}T"
                ts_str += f"{hour_entry['time']['hour']:02d}:00:00Z"

                # Skip duplicate timestamps
                existing = conn.execute(
                    'SELECT id FROM net_traffic WHERE interface=? AND timestamp=?',
                    (name, ts_str)
                ).fetchone()
                if existing:
                    continue

                conn.execute(
                    'INSERT INTO net_traffic (interface, timestamp, rx_bytes, tx_bytes) VALUES (?,?,?,?)',
                    (name, ts_str, hour_entry['rx'], hour_entry['tx'])
                )
        conn.commit()
    except Exception:
        logger.exception('vnstat collection failed')
    finally:
        conn.close()


# ── nethogs collector ─────────────────────────────────────────────

# Regex: process_name/pid/uid  or  unknown PROTO/pid/uid
_NETHOGS_LINE_RE = re.compile(
    r'^(?P<proc>[^\t]+)/(?P<pid>\d+)/(\d+)\t(?P<sent>[\d.]+)\t(?P<recv>[\d.]+)$'
)
_NETHOGS_UNKNOWN_RE = re.compile(
    r'^unknown (?P<proto>\w+)/(?P<pid>\d+)/(\d+)\t(?P<sent>[\d.]+)\t(?P<recv>[\d.]+)$'
)


def _run_nethogs():
    """Run nethogs in tracemode with auto-restart on crash.

    If the nethogs process exits or crashes, this restarts it after a brief delay.
    """
    RESTART_DELAY = 10  # seconds between restart attempts

    while not _stop.is_set():
        try:
            _run_nethogs_once()
        except Exception:
            logger.exception('nethogs collector crashed, restarting in %ss', RESTART_DELAY)
        if not _stop.is_set():
            _stop.wait(RESTART_DELAY)


def _run_nethogs_once():
    """Single nethogs session: parse output and store into net_process."""
    conn = _get_conn()
    try:
        # Use the first non-tailscale iface for nethogs (it monitors one iface at a time)
        primary_iface = next(
            (i for i in MONITOR_IFACES if 'tailscale' not in i),
            MONITOR_IFACES[0] if MONITOR_IFACES else 'eth0'
        )
        proc = subprocess.Popen(
            ['nethogs', '-t', '-d', str(NETHOGS_INTERVAL), primary_iface],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True
        )
        current_snapshot = {}
        ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

        start = time.time()
        while not _stop.is_set():
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    logger.warning('nethogs process exited unexpectedly (rc=%s)', proc.returncode)
                    break
                continue

            line = line.strip()
            if not line or line == 'Refreshing:':
                continue

            # Parse process line
            m = _NETHOGS_LINE_RE.match(line)
            if m:
                pid = int(m.group('pid'))
                proc_name = m.group('proc').strip()
                if proc_name.startswith('unknown '):
                    proc_name = 'unknown'
                    pid = 0
                sent = int(float(m.group('sent')) * 1024)  # KB -> bytes
                recv = int(float(m.group('recv')) * 1024)
                key = f"{proc_name}:{pid}"
                if key in current_snapshot:
                    current_snapshot[key]['sent'] += sent
                    current_snapshot[key]['recv'] += recv
                else:
                    current_snapshot[key] = {
                        'pid': pid, 'name': proc_name,
                        'sent': sent, 'recv': recv
                    }
                continue

            # Check for unknown format
            m = _NETHOGS_UNKNOWN_RE.match(line)
            if m:
                sent = int(float(m.group('sent')) * 1024)
                recv = int(float(m.group('recv')) * 1024)
                key = 'unknown:0'
                if key in current_snapshot:
                    current_snapshot[key]['sent'] += sent
                    current_snapshot[key]['recv'] += recv
                else:
                    current_snapshot[key] = {
                        'pid': 0, 'name': 'unknown',
                        'sent': sent, 'recv': recv
                    }
                continue

            # Check if one minute elapsed -> flush snapshot
            if time.time() - start >= NETHOGS_INTERVAL:
                ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
                for key, info in current_snapshot.items():
                    if info['sent'] > 0 or info['recv'] > 0:
                        conn.execute(
                            'INSERT INTO net_process (timestamp, pid, process_name, sent_bytes, recv_bytes) VALUES (?,?,?,?,?)',
                            (ts, info['pid'], info['name'], info['sent'], info['recv'])
                        )
                conn.commit()
                current_snapshot = {}
                start = time.time()

        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        logger.exception('nethogs collector crashed')
    finally:
        conn.close()


# ── ss collector ──────────────────────────────────────────────────

# Regex: Proto Recv-Q Send-Q Local Address:Port Remote Address:Port State PID/Program
# Example: tcp ESTAB 0 0 192.168.1.100:8850 1.2.3.4:54321 users:(("python",pid=12345,fd=7))
_SS_LINE_RE = re.compile(
    r'^(?P<proto>\w+)\s+\w+\s+\d+\s+\d+\s+'
    r'(?P<local>[^\s]+):(?P<lport>\d+)\s+'
    r'(?P<remote>[^\s]+):(?P<rport>\d+)\s+.*?'
    r'users:.*?\(\("(?P<proc>[^"]+)"'
)
_SS_PID_RE = re.compile(r'pid=(\d+)')

# Known safe ports (local services, common outbound)
LOCAL_SERVICE_PORTS = {8850, 8848, 8849, 18848, 80, 443, 8080, 53, 22}
IGNORE_IPS = {'127.0.0.1', '::1', '0.0.0.0', '*', '::', '10.255.255.254'}


def _collect_ss():
    """Run ss -tunap, parse connections, store into net_conn, detect anomalies."""
    conn = _get_conn()
    try:
        result = subprocess.run(
            ['ss', '-tunap'],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return

        ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        current_ips = set()  # remote IPs seen in this snapshot

        for line in result.stdout.strip().split('\n')[1:]:  # skip header
            if not line.strip():
                continue
            # Parse ss output
            parts = line.split()
            if len(parts) < 5:
                continue

            proto = parts[0]
            # Find local:port and remote:port fields
            local_str = ''
            remote_str = ''
            for p in parts:
                if ':' in p and not p.startswith('users:'):
                    if not local_str:
                        local_str = p
                    elif not remote_str:
                        remote_str = p
                        break

            if not remote_str:
                continue

            # Extract IP and port
            local_ip, _, local_port = local_str.rpartition(':')
            remote_ip, _, remote_port = remote_str.rpartition(':')

            # Skip local-only and ignored IPs
            if remote_ip in IGNORE_IPS or remote_ip.startswith('127.'):
                continue

            try:
                remote_port = int(remote_port)
            except ValueError:
                continue

            # Extract process info
            proc_line = ' '.join(parts)
            proc_name = 'unknown'
            pid = 0
            pm = _SS_LINE_RE.search(proc_line)
            if pm:
                proc_name = pm.group('proc')
                pidm = _SS_PID_RE.search(proc_line)
                if pidm:
                    pid = int(pidm.group(1))

            conn.execute(
                'INSERT INTO net_conn (timestamp, local_ip, local_port, remote_ip, remote_port, proto, pid, process_name) VALUES (?,?,?,?,?,?,?,?)',
                (ts, local_ip, int(local_port) if local_port.isdigit() else None,
                 remote_ip, remote_port, proto, pid, proc_name)
            )
            current_ips.add(remote_ip)

        conn.commit()

        # Anomaly detection: check for new IPs
        _detect_new_ips(conn, ts, current_ips)

    except Exception:
        logger.exception('ss collection failed')
    finally:
        conn.close()


def _detect_new_ips(conn, ts, current_ips):
    """Check if any current remote IPs have never been seen in the past 24h."""
    day_ago = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime('%Y-%m-%dT%H:%M:%SZ')

    # Load whitelist CIDRs
    try:
        whitelist = [row[0] for row in conn.execute('SELECT cidr FROM net_whitelist').fetchall()]
        whitelist_nets = [ipaddress.ip_network(w, strict=False) for w in whitelist]
    except Exception:
        whitelist_nets = []

    for ip in current_ips:
        if ip in IGNORE_IPS:
            continue

        # Skip IPv6 mapped addresses for whitelist check (strip ::ffff: prefix)
        clean_ip = ip.replace('[::ffff:', '').replace(']', '') if ip.startswith('[::ffff:') else ip
        # Remove brackets from IPv6 addresses
        clean_ip = clean_ip.strip('[]')

        # Check whitelist
        try:
            addr = ipaddress.ip_address(clean_ip)
            if any(addr in net for net in whitelist_nets):
                continue
        except ValueError:
            pass  # skip unrecognized IP formats

        # Check if this IP was seen in last 24h
        existing = conn.execute(
            'SELECT id FROM net_conn WHERE remote_ip=? AND timestamp < ? AND timestamp >= ? LIMIT 1',
            (ip, ts, day_ago)
        ).fetchone()

        if not existing:
            # Get the connection details for this IP from current snapshot
            detail = conn.execute(
                'SELECT remote_port, process_name FROM net_conn WHERE remote_ip=? AND timestamp=? LIMIT 1',
                (ip, ts)
            ).fetchone()

            if detail:
                port = detail['remote_port']
                proc = detail['process_name']

                # Check if already alerted for this IP today
                today_start = datetime.now(timezone.utc).strftime('%Y-%m-%dT00:00:00Z')
                alerted = conn.execute(
                    'SELECT id FROM net_alert WHERE remote_ip=? AND alert_type="new_ip" AND timestamp >= ?',
                    (ip, today_start)
                ).fetchone()

                if not alerted:
                    conn.execute(
                        'INSERT INTO net_alert (timestamp, alert_type, severity, remote_ip, port, process_name, detail) VALUES (?,?,?,?,?,?,?)',
                        (ts, 'new_ip', 'warning', ip, port, proc,
                         f'Remote IP {ip}:{port} connected via {proc}, not seen in last 24h')
                    )
    conn.commit()


# ── cleanup ───────────────────────────────────────────────────────

def _cleanup_old_data(conn):
    """Remove data older than retention period."""
    now = datetime.now(timezone.utc)

    for table, days in [
        ('net_traffic', RETENTION_TRAFFIC),
        ('net_process', RETENTION_PROCESS),
        ('net_conn', RETENTION_CONN),
        ('net_alert', RETENTION_ALERT),
    ]:
        cutoff = (now - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%SZ')
        conn.execute(f'DELETE FROM {table} WHERE timestamp < ?', (cutoff,))
    conn.commit()


# ── main loop ─────────────────────────────────────────────────────

def _vnstat_loop():
    """Run vnstat collection periodically."""
    while not _stop.is_set():
        _collect_vnstat()
        _stop.wait(VSTAT_INTERVAL)


def _ss_loop():
    """Run ss collection periodically."""
    while not _stop.is_set():
        _collect_ss()
        _stop.wait(SS_INTERVAL)


def _cleanup_loop():
    """Run cleanup periodically."""
    while not _stop.is_set():
        conn = _get_conn()
        try:
            _cleanup_old_data(conn)
        except Exception:
            logger.exception('network data cleanup failed')
        finally:
            conn.close()
        _stop.wait(CLEANUP_INTERVAL)


def start_net_collector():
    """Start all network collector background threads."""
    t1 = threading.Thread(target=_vnstat_loop, daemon=True, name='vnstat-collector')
    t2 = threading.Thread(target=_run_nethogs, daemon=True, name='nethogs-collector')
    t3 = threading.Thread(target=_ss_loop, daemon=True, name='ss-collector')
    t4 = threading.Thread(target=_cleanup_loop, daemon=True, name='net-cleanup')

    t1.start()
    t2.start()
    t3.start()
    t4.start()
