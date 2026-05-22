"""Dashboard - Personal system management homepage."""
import os
import sys
import threading

# Ensure backend/ is in path so Flask can find config, db, utils, routes
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from backend.app import create_app

app = create_app()

if __name__ == '__main__':
    from backend.config import CFG
    app.run(host=CFG['server']['host'], port=CFG['server']['port'], debug=CFG['server']['debug'])
