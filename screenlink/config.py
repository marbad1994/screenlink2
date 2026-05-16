"""
ScreenLink configuration — paths, defaults, load/save.
"""

import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "screenlink"
CONFIG_PATH = CONFIG_DIR / "config.json"

DP0_MAX_WIDTH = 5120  # Hard limit: DP-0 mode used is 5120x2880

DEFAULT_CONFIG = {
    "host_ip": "192.168.50.181",
    "ping_timeout": 1,
    "left": {
        "ip": "192.168.50.45",
        "width": 1366,
        "height": 768,
        "vnc_port": 5901,
        "remote_port": 5900,
        # "extend": host x0vncserver → remote viewer (left acts as extra monitor)
        # "remote": host vncviewer → remote machine (control the remote desktop)
        "mode": "extend",
        # VNC credentials for remote mode (macOS Screen Sharing needs these)
        "user": "",
        "password": "",
        # Start command runs when LEFT comes online. Supports template vars:
        # {ip} {port} {width} {height} {host_ip}
        "start_command": "",
        # Stop command runs on teardown. Useful for SSH cleanup on remote.
        # Same template vars as start_command.
        "stop_command": "",
    },
    "right": {
        "ip": "192.168.50.22",
        "width": 1440,
        "height": 900,
        "vnc_port": 5903,
        "remote_port": 5900,
        "mode": "extend",
        "user": "",
        "password": "",
        "start_command": "",
        "stop_command": "",
    },
    "middle": {
        "width": 1920,
        "height": 1080,
    },
}


def load_config():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH) as f:
                cfg = json.load(f)
            # Merge with defaults to fill in any missing keys
            for key, default in DEFAULT_CONFIG.items():
                if key not in cfg:
                    cfg[key] = default
                elif isinstance(default, dict):
                    for k, v in default.items():
                        cfg[key].setdefault(k, v)
            return cfg
        except Exception as e:
            print(f"Config load error: {e}, using defaults")
    save_config(DEFAULT_CONFIG)
    return json.loads(json.dumps(DEFAULT_CONFIG))


def save_config(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
