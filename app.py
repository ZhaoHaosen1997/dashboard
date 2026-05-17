"""Dashboard - 个人系统管理首页"""
import os, sqlite3
from flask import Flask, request, jsonify, g, send_from_directory
from flask_cors import CORS
import requests

app = Flask(__name__, template_folder='templates')
CORS(app)
DB_PATH = os.path.join(os.path.dirname(__file__), 'config.db')

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(e):
    db = g.pop('db', None)
    if db: db.close()

def init_db():
    if os.path.exists(DB_PATH): return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE systems (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, url TEXT NOT NULL,
        port INTEGER, description TEXT, icon TEXT DEFAULT 'box', color TEXT DEFAULT '#3b82f6',
        sort_order INTEGER DEFAULT 0, is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    defaults = [
        ('PrintFlow-3D', 'http://localhost:8848', 8848, '3D打印副业管理系统', 'printer', '#10b981', 1),
        ('Usage Data Viewer', 'http://localhost:8849', 8849, '字节API使用量查看', 'bar-chart-2', '#f59e0b', 2)]
    for d in defaults:
        c.execute('INSERT INTO systems (name,url,port,description,icon,color,sort_order) VALUES (?,?,?,?,?,?,?)', d)
    conn.commit(); conn.close()

@app.route('/api/systems')
def get_systems():
    db = get_db()
    cur = db.execute('SELECT * FROM systems ORDER BY sort_order, id')
    return jsonify([dict(r) for r in cur.fetchall()])

@app.route('/api/systems', methods=['POST'])
def create_system():
    d = request.json
    db = get_db()
    cur = db.execute('SELECT MAX(sort_order) FROM systems')
    max_o = cur.fetchone()[0] or 0
    cur = db.execute('INSERT INTO systems (name,url,port,description,icon,color,sort_order) VALUES (?,?,?,?,?,?,?)',
        (d['name'], d['url'], d.get('port'), d.get('description',''), d.get('icon','box'), d.get('color','#3b82f6'), max_o+1))
    db.commit()
    cur = db.execute('SELECT * FROM systems WHERE id=?', (cur.lastrowid,))
    return jsonify(dict(cur.fetchone())), 201

@app.route('/api/systems/<int:sid>', methods=['PUT'])
def update_system(sid):
    d = request.json
    db = get_db()
    db.execute('UPDATE systems SET name=?,url=?,port=?,description=?,icon=?,color=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',
        (d['name'], d['url'], d.get('port'), d.get('description',''), d.get('icon','box'), d.get('color','#3b82f6'), sid))
    db.commit()
    cur = db.execute('SELECT * FROM systems WHERE id=?', (sid,))
    return jsonify(dict(cur.fetchone()))

@app.route('/api/systems/<int:sid>', methods=['DELETE'])
def delete_system(sid):
    db = get_db()
    db.execute('DELETE FROM systems WHERE id=?', (sid,))
    db.commit()
    return jsonify({'ok': True})

@app.route('/api/systems/reorder', methods=['PATCH'])
def reorder():
    db = get_db()
    for item in request.json.get('orders', []):
        db.execute('UPDATE systems SET sort_order=? WHERE id=?', (item['sort_order'], item['id']))
    db.commit()
    return jsonify({'ok': True})

@app.route('/api/systems/<int:sid>/status')
def check_status(sid):
    db = get_db()
    cur = db.execute('SELECT url FROM systems WHERE id=?', (sid,))
    row = cur.fetchone()
    if not row: return jsonify({'error': 'Not found'}), 404
    try:
        r = requests.head(row['url'], timeout=3)
        online = r.status_code < 500
    except: online = False
    return jsonify({'id': sid, 'online': online})

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.dirname(__file__), 'favicon.ico', mimetype='image/x-icon')

@app.route('/')
def index():
    return send_from_directory(os.path.dirname(__file__), 'templates/index.html')

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=8850, debug=True)
