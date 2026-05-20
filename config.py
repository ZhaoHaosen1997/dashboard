"""Configuration loader - reads config.yml and provides CFG dict."""
import os
import yaml

def load_config():
    path = os.path.join(os.path.dirname(__file__), 'config.yml')
    with open(path, 'r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f)
    # Expand ~ in key_dir
    cfg['encryption']['key_dir'] = os.path.expanduser(cfg['encryption']['key_dir'])
    # Derive paths
    cfg['database']['abs_path'] = os.path.join(os.path.dirname(__file__), cfg['database']['path'])
    cfg['encryption']['key_file'] = os.path.join(cfg['encryption']['key_dir'], '.key')
    return cfg

CFG = load_config()
