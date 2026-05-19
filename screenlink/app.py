"""ScreenLink tray application — main orchestrator."""

import shutil
import subprocess

from PyQt6.QtWidgets import QSystemTrayIcon, QMenu, QMessageBox, QDialog
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import QTimer

# Support running this file directly (python app.py) for debugging.
try:
    from .config import load_config, save_config
    from .display_manager import DisplayManager
    from .helpers import run
    from .logging_setup import log, LOG_PATH, LOG_DIR
    from .ping_worker import PingWorker
    from .settings_dialog import SettingsDialog
except ImportError:
    # Fallback: add parent dir to path so absolute imports work
    import sys, os as _os
    _parent = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    if _parent not in sys.path:
        sys.path.insert(0, _parent)
    from screenlink.config import load_config, save_config
    from screenlink.display_manager import DisplayManager
    from screenlink.helpers import run
    from screenlink.logging_setup import log, LOG_PATH, LOG_DIR
    from screenlink.ping_worker import PingWorker
    from screenlink.settings_dialog import SettingsDialog


class ScreenLinkApp:
    def __init__(self, qapp):
        log.info("ScreenLinkApp.__init__ entry")
        self.qapp = qapp
        log.info("  loading config...")
        self.cfg = load_config()
        log.info("  config loaded: host_ip=%s left=%s right=%s",
                 self.cfg.get("host_ip"),
                 self.cfg["left"]["ip"], self.cfg["right"]["ip"])
        self.display = DisplayManager(self.cfg)
        self.remote_procs = {}
        self.left_alive = False
        self.right_alive = False

        log.info("  creating tray icon...")
        self.tray = QSystemTrayIcon()
        self.tray.setIcon(QIcon.fromTheme("video-display"))
        self.tray.setToolTip("ScreenLink")
        self.menu = QMenu()
        self.tray.setContextMenu(self.menu)
        log.info("  showing tray icon...")
        self.tray.show()
        log.info("  tray visible=%s", self.tray.isVisible())

        log.info("  setting up refresh timer (10s)...")
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.refresh_status)
        self.refresh_timer.start(10000)

        log.info("  scheduling initial start() in 200ms...")
        QTimer.singleShot(200, self.start)
        log.info("ScreenLinkApp.__init__ exit")

    def rebuild_menu(self):
        self.menu.clear()
        status = self.menu.addAction(f"Layout: {self.display.layout or 'idle'}")
        status.setEnabled(False)

        ls = "online" if self.left_alive else "offline"
        rs = "online" if self.right_alive else "offline"
        self.menu.addAction(f"  LEFT  ({self.cfg['left']['ip']}): {ls}").setEnabled(False)
        self.menu.addAction(f"  RIGHT ({self.cfg['right']['ip']}): {rs}").setEnabled(False)

        self.menu.addSeparator()

        # --- Mode toggle: LEFT ---
        left_mode = self.cfg["left"].get("mode", "extend")
        a = self.menu.addAction("LEFT: Remote Control")
        a.setCheckable(True)
        a.setChecked(left_mode == "remote")
        a.setEnabled(self.left_alive)
        a.triggered.connect(lambda checked, k="left": self.toggle_mode(k, checked))
        self.menu.addAction(a)

        # --- Mode toggle: RIGHT ---
        right_mode = self.cfg["right"].get("mode", "extend")
        b = self.menu.addAction("RIGHT: Remote Control")
        b.setCheckable(True)
        b.setChecked(right_mode == "remote")
        b.setEnabled(self.right_alive)
        b.triggered.connect(lambda checked, k="right": self.toggle_mode(k, checked))
        self.menu.addAction(b)

        self.menu.addSeparator()

        r = self.menu.addAction("Restart")
        r.triggered.connect(self.restart)
        s = self.menu.addAction("Stop")
        s.triggered.connect(self.stop)
        self.menu.addSeparator()
        sg = self.menu.addAction("Settings...")
        sg.triggered.connect(self.open_settings)
        vl = self.menu.addAction("View Logs")
        vl.triggered.connect(self.view_logs)
        q = self.menu.addAction("Quit")
        q.triggered.connect(self.quit)

    def view_logs(self):
        """Open the log file in the user's default text viewer."""
        log.info("Opening logs at %s", LOG_PATH)
        # Try xdg-open first; fall back to xfce4-terminal tailing the log
        if shutil.which("xdg-open"):
            subprocess.Popen(["xdg-open", str(LOG_PATH)])
        elif shutil.which("xfce4-terminal"):
            subprocess.Popen(["xfce4-terminal", "-e", f"tail -f {LOG_PATH}"])
        else:
            QMessageBox.information(None, "Logs",
                f"Log file: {LOG_PATH}\nProcess logs: {LOG_DIR}/")

    def start(self):
        """Kick off a background ping; layout is applied when it returns."""
        log.info("=== start() called ===")
        worker = PingWorker(
            self.cfg["left"]["ip"], self.cfg["right"]["ip"],
            self.cfg["ping_timeout"]
        )
        worker.finished_pinging.connect(self._on_ping_done)
        worker.finished.connect(worker.deleteLater)
        self._ping_worker = worker  # hold reference so it isn't GC'd
        worker.start()

    def _on_ping_done(self, left_alive, right_alive):
        self.left_alive = left_alive
        self.right_alive = right_alive
        if left_alive and right_alive:
            layout = "triple"
        elif left_alive:
            layout = "left_only"
        elif right_alive:
            layout = "right_only"
        else:
            layout = "single"
        log.info("Detected layout: %s (left=%s, right=%s)",
                 layout, left_alive, right_alive)
        try:
            self.display.apply_layout(layout)
            # xfwm4 needs --replace to pick up new monitor boundaries
            # (otherwise fullscreen spans all screens).  The layout is
            # now stable (MIDDLE never moves) so the flicker is minimal.
            if shutil.which("xfwm4"):
                subprocess.Popen(
                    ["xfwm4", "--replace"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            self.tray.showMessage("ScreenLink", f"Layout: {layout}",
                QSystemTrayIcon.MessageIcon.Information, 3000)
        except Exception as e:
            log.exception("Apply layout error: %s", e)
            self.tray.showMessage("ScreenLink error", str(e),
                QSystemTrayIcon.MessageIcon.Critical, 5000)
        self.rebuild_menu()

    def refresh_status(self):
        """Re-ping in background; apply_layout only fires if availability changed."""
        worker = PingWorker(
            self.cfg["left"]["ip"], self.cfg["right"]["ip"],
            self.cfg["ping_timeout"]
        )
        worker.finished_pinging.connect(self._on_refresh_ping)
        worker.finished.connect(worker.deleteLater)
        self._refresh_worker = worker
        worker.start()

    def _on_refresh_ping(self, new_left, new_right):
        if (new_left, new_right) != (self.left_alive, self.right_alive):
            log.info("Availability changed: left %s->%s, right %s->%s",
                     self.left_alive, new_left, self.right_alive, new_right)
            self.left_alive = new_left
            self.right_alive = new_right
            self._on_ping_done(new_left, new_right)
        else:
            self.rebuild_menu()

    def stop(self):
        self.display.teardown()
        run(["nvidia-settings", "--assign",
             f"CurrentMetaMode=HDMI-0: {self.cfg['middle']['width']}x{self.cfg['middle']['height']} +0+0"])
        self.display.layout = "stopped"
        self.rebuild_menu()

    def restart(self):
        self.stop()
        QTimer.singleShot(500, self.start)

    def toggle_mode(self, key, checked):
        """Switch between extend (unchecked) and remote (checked) for a client."""
        new_mode = "remote" if checked else "extend"
        old_mode = self.cfg[key].get("mode", "extend")
        if new_mode == old_mode:
            return

        log.info("Toggling %s mode: %s -> %s", key, old_mode, new_mode)
        self.cfg[key]["mode"] = new_mode
        save_config(self.cfg)
        self.display.cfg = self.cfg
        # Re-apply layout to switch the VNC/viewer processes
        self.restart()

    def open_settings(self):
        dlg = SettingsDialog(self.cfg)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.cfg = dlg.get_config()
            save_config(self.cfg)
            self.display.cfg = self.cfg
            self.restart()

    def quit(self):
        self.stop()
        for proc in self.remote_procs.values():
            try:
                proc.terminate()
            except Exception:
                pass
        self.tray.hide()
        self.qapp.quit()
