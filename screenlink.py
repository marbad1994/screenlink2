#!/usr/bin/env python3
"""
ScreenLink — Dynamic multi-display orchestration with system tray.

Daemonizes on launch.  Logs go to /tmp/screenlink.log.
"""

import os
import sys


def main():
    from screenlink.logging_setup import log, LOG_PATH, LOG_DIR
    from screenlink.config import CONFIG_PATH

    # -- daemonize (double-fork) -------------------------------------------
    if os.fork() > 0:
        return  # parent exits immediately

    os.setsid()
    if os.fork() > 0:
        return  # second parent exits

    # Redirect stdin/stdout/stderr to /dev/null
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, sys.stdin.fileno())
    os.dup2(devnull, sys.stdout.fileno())
    os.dup2(devnull, sys.stderr.fileno())
    os.close(devnull)
    # --------------------------------------------------------------------

    from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMessageBox
    from screenlink.app import ScreenLinkApp

    log.info("=" * 60)
    log.info("ScreenLink daemon started (pid=%d)", os.getpid())
    log.info("Log file: %s", LOG_PATH)
    log.info("Process logs dir: %s", LOG_DIR)
    log.info("Config file: %s", CONFIG_PATH)
    log.info("=" * 60)

    def excepthook(exc_type, exc_value, exc_tb):
        log.critical("UNCAUGHT EXCEPTION", exc_info=(exc_type, exc_value, exc_tb))
        sys.__excepthook__(exc_type, exc_value, exc_tb)
    sys.excepthook = excepthook

    log.info("Creating QApplication...")
    app = QApplication(sys.argv)
    log.info("QApplication created.")
    app.setQuitOnLastWindowClosed(False)

    log.info("Checking system tray availability...")
    if not QSystemTrayIcon.isSystemTrayAvailable():
        log.error("No system tray detected!")
        QMessageBox.critical(None, "ScreenLink",
            "No system tray detected on this system.")
        sys.exit(1)
    log.info("System tray available.")

    log.info("Instantiating ScreenLinkApp...")
    sl_app = ScreenLinkApp(app)
    log.info("ScreenLinkApp instantiated, entering event loop.")
    rc = app.exec()
    log.info("Event loop exited with rc=%d", rc)
    sys.exit(rc)


if __name__ == "__main__":
    # Print log location *before* detaching so the user knows where to look
    print(f"ScreenLink daemonizing — logs:  tail -f /tmp/screenlink.log")
    main()
