"""Routes package - exports all Blueprint instances."""
from routes.systems import systems_bp
from routes.wsl import wsl_bp
from routes.backup import backup_bp
from routes.webdav import webdav_bp

__all__ = ['systems_bp', 'wsl_bp', 'backup_bp', 'webdav_bp']
