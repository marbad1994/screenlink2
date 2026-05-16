"""
ScreenLink — Dynamic multi-display orchestration with system tray.

Package entry point is the top-level ``screenlink.py`` script.
"""

from .app import ScreenLinkApp
from .config import load_config, save_config, DEFAULT_CONFIG, DP0_MAX_WIDTH
from .display_manager import DisplayManager
from .helpers import run, ping, render_command
from .logging_setup import log, LOG_PATH, LOG_DIR
from .ping_worker import PingWorker
from .settings_dialog import SettingsDialog, CollapsibleGroupBox

__all__ = [
    "ScreenLinkApp",
    "DisplayManager",
    "PingWorker",
    "SettingsDialog",
    "CollapsibleGroupBox",
    "load_config",
    "save_config",
    "DEFAULT_CONFIG",
    "DP0_MAX_WIDTH",
    "run",
    "ping",
    "render_command",
    "log",
    "LOG_PATH",
    "LOG_DIR",
]
