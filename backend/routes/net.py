"""Network monitoring API routes."""
from datetime import datetime, timezone, timedelta

from flask import Blueprint, jsonify, request

from db import get_db

net_bp = Blueprint('net', __name__)


@net_bp.route('/api/net/summary')
def net_summary():
    """Quick overview: today's total traffic, top processes, new IPs."""
    db = get_db()
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    hours = request.args.get('hours', 24, type=int)

    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime('%Y-%m-%dT%H:%M:%SZ')

    # Total traffic per interface
    traffic = db.execute('''
        SELECT interface, SUM(rx_bytes) as rx, SUM(tx_bytes) as tx
        FROM net_traffic
        WHERE timestamp >= ?
        GROUP BY interface
        ORDER BY rx DESC
    ''', (since,)).fetchall()

    # Top processes by traffic
    top_procs = db.execute('''
        SELECT process_name, SUM(sent_bytes) as sent, SUM(recv_bytes) as recv,
               COUNT(*) as samples
        FROM net_process
        WHERE timestamp >= ?
        GROUP BY process_name
        ORDER BY (SUM(sent_bytes) + SUM(recv_bytes)) DESC
        LIMIT 10
    ''', (since,)).fetchall()

    # Recent alerts
    alerts = db.execute('''
        SELECT * FROM net_alert
        WHERE acknowledged = 0 AND timestamp >= ?
        ORDER BY timestamp DESC LIMIT 5
    ''', (since,)).fetchall()

    # Active connections count
    latest_ts = db.execute(
        'SELECT MAX(timestamp) as ts FROM net_conn'
    ).fetchone()
    conn_count = 0
    if latest_ts and latest_ts['ts']:
        conn_count = db.execute(
            'SELECT COUNT(*) as c FROM net_conn WHERE timestamp = ?',
            (latest_ts['ts'],)
        ).fetchone()['c']

    return jsonify({
        'traffic': [dict(r) for r in traffic],
        'top_processes': [dict(r) for r in top_procs],
        'recent_alerts': [dict(r) for r in alerts],
        'active_connections': conn_count,
        'hours': hours,
    })


@net_bp.route('/api/net/traffic')
def net_traffic():
    """Hourly/daily traffic data for charts."""
    db = get_db()
    days = request.args.get('days', 7, type=int)
    iface = request.args.get('interface', 'eth1')
    granularity = request.args.get('granularity', 'hour')  # hour or day

    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%SZ')

    if granularity == 'day':
        rows = db.execute('''
            SELECT DATE(timestamp) as date, interface,
                   SUM(rx_bytes) as rx, SUM(tx_bytes) as tx
            FROM net_traffic
            WHERE timestamp >= ? AND interface = ?
            GROUP BY date
            ORDER BY date
        ''', (since, iface)).fetchall()
    else:
        rows = db.execute('''
            SELECT timestamp, rx_bytes as rx, tx_bytes as tx
            FROM net_traffic
            WHERE timestamp >= ? AND interface = ?
            ORDER BY timestamp
        ''', (since, iface)).fetchall()

    return jsonify({
        'interface': iface,
        'granularity': granularity,
        'data': [dict(r) for r in rows],
    })


@net_bp.route('/api/net/processes')
def net_processes():
    """Per-process traffic breakdown."""
    db = get_db()
    hours = request.args.get('hours', 24, type=int)
    limit = request.args.get('limit', 20, type=int)

    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime('%Y-%m-%dT%H:%M:%SZ')

    # Aggregate per process
    rows = db.execute('''
        SELECT process_name, pid,
               SUM(sent_bytes) as sent, SUM(recv_bytes) as recv,
               COUNT(*) as samples
        FROM net_process
        WHERE timestamp >= ?
        GROUP BY process_name, pid
        ORDER BY (SUM(sent_bytes) + SUM(recv_bytes)) DESC
        LIMIT ?
    ''', (since, limit)).fetchall()

    # Hourly timeline for top 5 processes
    top5_names = [r['process_name'] for r in rows[:5]]
    timeline = []
    if top5_names:
        placeholders = ','.join('?' * len(top5_names))
        timeline_rows = db.execute(f'''
            SELECT timestamp, process_name,
                   SUM(sent_bytes) as sent, SUM(recv_bytes) as recv
            FROM net_process
            WHERE timestamp >= ? AND process_name IN ({placeholders})
            GROUP BY strftime('%Y-%m-%dT%H:00', timestamp), process_name
            ORDER BY timestamp
        ''', [since] + top5_names).fetchall()
        timeline = [dict(r) for r in timeline_rows]

    return jsonify({
        'hours': hours,
        'processes': [dict(r) for r in rows],
        'timeline': timeline,
    })


@net_bp.route('/api/net/connections')
def net_connections():
    """Recent connection snapshots with IP analysis."""
    db = get_db()
    hours = request.args.get('hours', 24, type=int)
    limit = request.args.get('limit', 100, type=int)
    group_by = request.args.get('group_by', 'ip')  # ip or process

    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime('%Y-%m-%dT%H:%M:%SZ')

    if group_by == 'ip':
        # Unique remote IPs ranked by connection count
        rows = db.execute('''
            SELECT remote_ip, COUNT(*) as conn_count,
                   GROUP_CONCAT(DISTINCT remote_port) as ports,
                   GROUP_CONCAT(DISTINCT process_name) as processes,
                   MAX(timestamp) as last_seen
            FROM net_conn
            WHERE timestamp >= ?
            GROUP BY remote_ip
            ORDER BY conn_count DESC
            LIMIT ?
        ''', (since, limit)).fetchall()
    else:
        # Grouped by process
        rows = db.execute('''
            SELECT process_name, pid,
                   COUNT(DISTINCT remote_ip) as unique_ips,
                   COUNT(*) as conn_count,
                   GROUP_CONCAT(DISTINCT remote_port) as ports
            FROM net_conn
            WHERE timestamp >= ?
            GROUP BY process_name, pid
            ORDER BY conn_count DESC
            LIMIT ?
        ''', (since, limit)).fetchall()

    return jsonify({
        'hours': hours,
        'group_by': group_by,
        'connections': [dict(r) for r in rows],
    })


@net_bp.route('/api/net/alerts')
def net_alerts():
    """Network anomaly alerts."""
    db = get_db()
    days = request.args.get('days', 7, type=int)
    only_unack = request.args.get('unacknowledged', '1') == '1'

    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%SZ')

    query = 'SELECT * FROM net_alert WHERE timestamp >= ?'
    params = [since]
    if only_unack:
        query += ' AND acknowledged = 0'
    query += ' ORDER BY timestamp DESC'
    rows = db.execute(query, params).fetchall()

    return jsonify({
        'days': days,
        'only_unacknowledged': only_unack,
        'alerts': [dict(r) for r in rows],
    })


@net_bp.route('/api/net/alerts/<int:alert_id>/ack', methods=['POST'])
def ack_alert(alert_id):
    """Acknowledge an alert."""
    db = get_db()
    db.execute('UPDATE net_alert SET acknowledged = 1 WHERE id = ?', (alert_id,))
    db.commit()
    return jsonify({'status': 'ok'})


@net_bp.route('/api/net/whitelist')
def net_whitelist():
    """Get all whitelist entries."""
    db = get_db()
    rows = db.execute('SELECT * FROM net_whitelist ORDER BY id').fetchall()
    return jsonify([dict(r) for r in rows])


@net_bp.route('/api/net/whitelist', methods=['POST'])
def add_whitelist():
    """Add a whitelist CIDR."""
    db = get_db()
    data = request.get_json()
    cidr = data.get('cidr', '').strip()
    note = data.get('note', '').strip()
    if not cidr:
        return jsonify({'error': 'cidr required'}), 400
    try:
        db.execute('INSERT INTO net_whitelist (cidr, note) VALUES (?,?)', (cidr, note))
        db.commit()
        return jsonify({'status': 'ok'}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@net_bp.route('/api/net/whitelist/<int:wid>', methods=['DELETE'])
def delete_whitelist(wid):
    """Delete a whitelist entry."""
    db = get_db()
    db.execute('DELETE FROM net_whitelist WHERE id = ?', (wid,))
    db.commit()
    return jsonify({'status': 'ok'})
