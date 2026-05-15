#!/usr/bin/env python3
"""
ScreenLink GUI — Dynamic multi-display orchestration with system tray.

Features:
- Auto-detects which clients are online via ping at startup
- Configures display layout (1/2/3 screens) accordingly
- Validates total width <= 5120 (DP-0 mode limit)
- Per-client start command (e.g. SSH+launch VNC viewer on the laptop)
- Tray menu with start/stop, remote sessions, and settings
"""

import sys
import os
import json
import socket
import subprocess
import shutil
import logging
import traceback
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QSpinBox, QFormLayout, QMessageBox,
    QGroupBox, QPlainTextEdit, QWidget, QComboBox, QScrollArea
)
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtCore import QTimer, Qt, QThread, pyqtSignal


# --------------------------------------------------------------------------
# Logging — write everything to /tmp/screenlink.log AND stderr
# --------------------------------------------------------------------------
LOG_PATH = Path("/tmp/screenlink.log")
LOG_DIR = Path("/tmp/screenlink-procs")  # captures x0vncserver + start_command output
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, mode="w"),  # truncate on each run
        logging.StreamHandler(sys.stderr),
    ],
)
log = logging.getLogger("screenlink")


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
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


# --------------------------------------------------------------------------
# System helpers
# --------------------------------------------------------------------------
def run(cmd, timeout=8):
    """Run a command synchronously with timeout. Always logs result."""
    log.info("$ %s", " ".join(cmd))
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        if result.returncode != 0:
            log.warning("  rc=%d  stderr=%s", result.returncode,
                        (result.stderr or "").strip())
        elif result.stdout.strip():
            log.debug("  stdout=%s", result.stdout.strip())
        return result
    except subprocess.TimeoutExpired:
        log.error("  TIMEOUT after %ds: %s", timeout, " ".join(cmd))
        return None
    except FileNotFoundError as e:
        log.error("  COMMAND NOT FOUND: %s", e)
        return None
    except Exception as e:
        log.exception("  ERROR running %s: %s", cmd, e)
        return None


def ping(ip, timeout=1):
    if not ip:
        return False
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", str(timeout), ip],
            capture_output=True, timeout=timeout + 1
        )
        alive = result.returncode == 0
        log.debug("ping %s -> %s", ip, "alive" if alive else "dead")
        return alive
    except Exception as e:
        log.warning("ping %s failed: %s", ip, e)
        return False


def render_command(template, vars_dict):
    """Substitute {var} placeholders. Returns None if template is empty."""
    template = (template or "").strip()
    if not template:
        return None
    try:
        return template.format(**vars_dict)
    except KeyError as e:
        log.error("Unknown variable in start_command: %s", e)
        return template


# --------------------------------------------------------------------------
# Background ping worker — keeps the GUI thread responsive
# --------------------------------------------------------------------------
class PingWorker(QThread):
    finished_pinging = pyqtSignal(bool, bool)  # left_alive, right_alive

    def __init__(self, left_ip, right_ip, timeout=1):
        super().__init__()
        self.left_ip = left_ip
        self.right_ip = right_ip
        self.timeout = timeout

    def run(self):
        log.info("PingWorker.run: pinging left=%s right=%s timeout=%ds",
                 self.left_ip, self.right_ip, self.timeout)
        try:
            left = ping(self.left_ip, self.timeout)
            right = ping(self.right_ip, self.timeout)
            log.info("PingWorker.run: results left=%s right=%s", left, right)
            self.finished_pinging.emit(left, right)
        except Exception:
            log.exception("PingWorker crashed")
            self.finished_pinging.emit(False, False)


# --------------------------------------------------------------------------
# Display layout management
# --------------------------------------------------------------------------
class DisplayManager:
    def __init__(self, cfg):
        self.cfg = cfg
        self.layout = None
        self.vnc_procs = {}          # x0vncserver processes (extend mode)
        self.start_procs = {}        # per-client start_command processes
        self.remote_viewer_procs = {}  # vncviewer processes (remote mode)

    def determine_layout(self):
        left_alive = ping(self.cfg["left"]["ip"], self.cfg["ping_timeout"])
        right_alive = ping(self.cfg["right"]["ip"], self.cfg["ping_timeout"])
        if left_alive and right_alive:
            return "triple", left_alive, right_alive
        if left_alive:
            return "left_only", left_alive, right_alive
        if right_alive:
            return "right_only", left_alive, right_alive
        return "single", left_alive, right_alive

    def apply_layout(self, layout):
        self.layout = layout
        L = self.cfg["left"]
        R = self.cfg["right"]
        M = self.cfg["middle"]

        # All multi-screen layouts use DP-0 at 5120x2880 for simplicity.
        # Section positions vary; HDMI position vs DP-0 origin varies.
        if layout == "triple":
            metamode = (
                f"HDMI-0: {M['width']}x{M['height']} +{L['width']}+0, "
                f"DP-0: 5120x2880 +0+0"
            )
            sections = [
                ("LEFT",   L["width"], L["height"], 0,                       0, "none",   False),
                ("MIDDLE", M["width"], M["height"], L["width"],              0, "HDMI-0", True),
                ("RIGHT",  R["width"], R["height"], L["width"] + M["width"], 0, "none",   False),
            ]
        elif layout == "left_only":
            metamode = (
                f"HDMI-0: {M['width']}x{M['height']} +{L['width']}+0, "
                f"DP-0: 5120x2880 +0+0"
            )
            sections = [
                ("LEFT",   L["width"], L["height"], 0,          0, "none",   False),
                ("MIDDLE", M["width"], M["height"], L["width"], 0, "HDMI-0", True),
            ]
        elif layout == "right_only":
            # DP-0 placed right of HDMI so RIGHT lives at +middle_width
            metamode = (
                f"HDMI-0: {M['width']}x{M['height']} +0+0, "
                f"DP-0: 5120x2880 +{M['width']}+0"
            )
            sections = [
                ("MIDDLE", M["width"], M["height"], 0,          0, "HDMI-0", True),
                ("RIGHT",  R["width"], R["height"], M["width"], 0, "none",   False),
            ]
        else:  # single
            metamode = f"HDMI-0: {M['width']}x{M['height']} +0+0"
            sections = [
                ("MIDDLE", M["width"], M["height"], 0, 0, "HDMI-0", True),
            ]

        run(["nvidia-settings", "--assign", f"CurrentMetaMode={metamode}"])

        # Reset our logical monitors
        for name in ("LEFT", "MIDDLE", "RIGHT"):
            run(["xrandr", "--delmonitor", name])
        for name, w, h, x, y, output, primary in sections:
            mon_name = f"*{name}" if primary else name
            geom = f"{w}/300x{h}/200+{x}+{y}"
            run(["xrandr", "--setmonitor", mon_name, geom, output])

        # VNC servers + client start commands
        self.stop_vnc_servers()
        self.stop_start_commands()
        host_ip = self.cfg.get("host_ip", "")
        for name, w, h, x, y, output, primary in sections:
            if name == "LEFT":
                self._start_section("left", w, h, x, y, L, host_ip)
            elif name == "RIGHT":
                self._start_section("right", w, h, x, y, R, host_ip)

    def _start_section(self, key, w, h, x, y, client_cfg, host_ip):
        mode = client_cfg.get("mode", "extend")

        if mode == "remote":
            self._start_section_remote(key, w, h, x, y, client_cfg, host_ip)
        else:
            self._start_section_extend(key, w, h, x, y, client_cfg, host_ip)

    def _start_section_extend(self, key, w, h, x, y, client_cfg, host_ip):
        """Extend mode: host runs x0vncserver clipping this section.
           Remote machine connects to host with a VNC viewer."""
        # 0. Run stop_command first (clean up previous remote session)
        self._run_stop_command(key, client_cfg, host_ip)

        # 1. Start x0vncserver — capture output so we can see what failed
        port = client_cfg["vnc_port"]
        subprocess.run(["pkill", "-f", f"x0vncserver.*-rfbport {port}"],
                       capture_output=True)
        cmd = [
            "x0vncserver",
            "FrameRate=30", "CompareFB=1", "SecurityTypes=none",
            "AcceptPointerEvents=True", "AlwaysShared=on", "MaxProcessorUsage=70",
            "-geometry", f"{w}x{h}+{x}+{y}",
            "-rfbport", str(port),
        ]
        log.info("Starting VNC for %s: %s", key, " ".join(cmd))
        vnc_log = open(LOG_DIR / f"x0vncserver-{key}.log", "w")
        try:
            self.vnc_procs[key] = subprocess.Popen(
                cmd, stdout=vnc_log, stderr=subprocess.STDOUT
            )
            log.info("  PID=%d, output -> %s",
                     self.vnc_procs[key].pid, vnc_log.name)
        except Exception as e:
            log.exception("Failed to spawn x0vncserver for %s: %s", key, e)
            return

        # 2. Run start_command if defined
        cmd_template = client_cfg.get("start_command", "")
        rendered = render_command(cmd_template, {
            "ip": client_cfg["ip"],
            "port": port,
            "width": w,
            "height": h,
            "host_ip": host_ip,
        })
        if rendered:
            log.info("Start command for %s: %s", key, rendered)
            sc_log = open(LOG_DIR / f"start-{key}.log", "w")
            try:
                self.start_procs[key] = subprocess.Popen(
                    rendered, shell=True,
                    stdout=sc_log, stderr=subprocess.STDOUT
                )
                log.info("  PID=%d, output -> %s",
                         self.start_procs[key].pid, sc_log.name)
            except Exception as e:
                log.exception("Failed to run start_command for %s: %s", key, e)

    def _start_section_remote(self, key, w, h, x, y, client_cfg, host_ip):
        """Remote mode: host opens a vncviewer window positioned at this section,
           connecting TO the remote machine's VNC server."""
        ip = client_cfg["ip"]
        port = client_cfg.get("remote_port", 5900)

        # 0. Run stop_command first (clean up previous remote session)
        self._run_stop_command(key, client_cfg, host_ip)

        if not shutil.which("vncviewer"):
            log.error("Remote mode for %s: vncviewer not found!", key)
            return

        target = f"{ip}::{port}" if port != 5900 else ip
        # TigerVNC vncviewer accepts -geometry WxH+X+Y for size + position
        geom = f"{w}x{h}+{x}+{y}"
        cmd = ["vncviewer", "-geometry", geom, "--FullScreen=0", target]
        log.info("Remote mode for %s: %s", key, " ".join(cmd))

        # Pass VNC credentials for macOS Screen Sharing
        env = os.environ.copy()
        user = client_cfg.get("user", "").strip()
        pw = client_cfg.get("password", "").strip()
        if user:
            env["VNC_USERNAME"] = user
        if pw:
            env["VNC_PASSWORD"] = pw

        rv_log = open(LOG_DIR / f"remote-viewer-{key}.log", "w")
        try:
            self.remote_viewer_procs[key] = subprocess.Popen(
                cmd, stdout=rv_log, stderr=subprocess.STDOUT, env=env
            )
            viewer_pid = self.remote_viewer_procs[key].pid
            log.info("  PID=%d, output -> %s", viewer_pid, rv_log.name)

            # Push vncviewer to background (minimize) so it doesn't steal focus
            if shutil.which("xdotool"):
                subprocess.Popen(
                    ["xdotool", "search", "--sync", "--pid", str(viewer_pid),
                     "windowminimize", "%@"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
        except Exception as e:
            log.exception("Failed to spawn vncviewer for %s: %s", key, e)

        # 2. Run start_command if defined
        cmd_template = client_cfg.get("start_command", "")
        rendered = render_command(cmd_template, {
            "ip": client_cfg["ip"],
            "port": port,
            "width": w,
            "height": h,
            "host_ip": host_ip,
        })
        if rendered:
            log.info("Start command for %s: %s", key, rendered)
            sc_log = open(LOG_DIR / f"start-{key}.log", "w")
            try:
                self.start_procs[key] = subprocess.Popen(
                    rendered, shell=True,
                    stdout=sc_log, stderr=subprocess.STDOUT
                )
                log.info("  PID=%d, output -> %s",
                         self.start_procs[key].pid, sc_log.name)
            except Exception as e:
                log.exception("Failed to run start_command for %s: %s", key, e)

    def _run_stop_command(self, key, client_cfg, host_ip):
        """Run the client's stop_command once (e.g., SSH cleanup on remote)."""
        cmd_template = client_cfg.get("stop_command", "")
        if not cmd_template:
            return
        port = client_cfg.get("vnc_port", 5900)
        rendered = render_command(cmd_template, {
            "ip": client_cfg["ip"],
            "port": port,
            "width": client_cfg.get("width", 0),
            "height": client_cfg.get("height", 0),
            "host_ip": host_ip,
        })
        if rendered:
            log.info("Stop command for %s: %s", key, rendered)
            try:
                subprocess.run(rendered, shell=True, timeout=10, capture_output=True)
            except Exception as e:
                log.warning("Stop command for %s failed: %s", key, e)

    def stop_vnc_servers(self):
        for proc in self.vnc_procs.values():
            try:
                proc.terminate()
            except Exception:
                pass
        self.vnc_procs.clear()
        subprocess.run(["pkill", "-f", "x0vncserver"], capture_output=True)

    def stop_start_commands(self):
        for proc in self.start_procs.values():
            try:
                proc.terminate()
            except Exception:
                pass
        self.start_procs.clear()

    def stop_remote_viewers(self):
        for proc in self.remote_viewer_procs.values():
            try:
                proc.terminate()
            except Exception:
                pass
        self.remote_viewer_procs.clear()

    def teardown(self):
        # Run stop_commands for all clients before killing local procs
        host_ip = self.cfg.get("host_ip", "")
        for key in ("left", "right"):
            self._run_stop_command(key, self.cfg.get(key, {}), host_ip)

        self.stop_vnc_servers()
        self.stop_start_commands()
        self.stop_remote_viewers()
        for name in ("LEFT", "MIDDLE", "RIGHT"):
            run(["xrandr", "--delmonitor", name])


# --------------------------------------------------------------------------
# Collapsible group box — ticking the checkbox shows/hides content
# --------------------------------------------------------------------------
class CollapsibleGroupBox(QGroupBox):
    def __init__(self, title, parent=None):
        super().__init__(title, parent)
        self.setCheckable(True)
        self.setChecked(True)
        self.toggled.connect(self._on_toggled)

    def _on_toggled(self, checked):
        for child in self.findChildren(QWidget):
            # Only hide direct children (skip grandchildren unless they are
            # part of a layout that is itself hidden)
            if child.parent() == self:
                child.setVisible(checked)
        # Force relayout of parent
        if self.parentWidget():
            self.parentWidget().updateGeometry()


# Settings dialog
# --------------------------------------------------------------------------
class SettingsDialog(QDialog):
    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("ScreenLink Settings")
        self.setMinimumWidth(560)
        self.resize(580, 700)

        # Scrollable content
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(0, 0, 0, 0)

        # Host IP
        host_box = CollapsibleGroupBox("Host")
        host_form = QFormLayout(host_box)
        self.host_ip = QLineEdit(cfg.get("host_ip", ""))
        host_form.addRow("Host IP (used as {host_ip}):", self.host_ip)
        root.addWidget(host_box)

        # LEFT
        self.left_widgets = self._build_client_box(
            "Left Client", cfg["left"], with_command=True
        )
        root.addWidget(self.left_widgets["box"])

        # MIDDLE — no start_command (it's your real screen)
        self.mid_widgets = self._build_middle_box(cfg["middle"])
        root.addWidget(self.mid_widgets["box"])

        # RIGHT
        self.right_widgets = self._build_client_box(
            "Right Client", cfg["right"], with_command=True
        )
        root.addWidget(self.right_widgets["box"])

        # Total width validation
        self.total_label = QLabel()
        self.total_label.setStyleSheet("font-weight: bold;")
        root.addWidget(self.total_label)

        # Buttons — create save_btn before _update_total runs (it toggles enabled state)
        btn_row = QHBoxLayout()
        self.save_btn = QPushButton("Save && Restart")
        cancel_btn = QPushButton("Cancel")
        self.save_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch(); btn_row.addWidget(cancel_btn); btn_row.addWidget(self.save_btn)
        root.addLayout(btn_row)

        # Wire change signals (must come after save_btn exists)
        for spin in (self.left_widgets["w"], self.mid_widgets["w"], self.right_widgets["w"]):
            spin.valueChanged.connect(self._update_total)
        self._update_total()

        scroll.setWidget(content)

        # Wrap scroll area as the dialog's only layout
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _build_client_box(self, title, client_cfg, with_command=False):
        box = CollapsibleGroupBox(title)
        form = QFormLayout(box)
        ip = QLineEdit(client_cfg["ip"])
        w = QSpinBox(); w.setRange(640, DP0_MAX_WIDTH); w.setValue(client_cfg["width"])
        h = QSpinBox(); h.setRange(480, 4320); h.setValue(client_cfg["height"])
        vnc_port = QSpinBox(); vnc_port.setRange(1024, 65535); vnc_port.setValue(client_cfg.get("vnc_port", 5900))
        remote_port = QSpinBox(); remote_port.setRange(1024, 65535); remote_port.setValue(client_cfg.get("remote_port", 5900))
        mode_combo = QComboBox()
        mode_combo.addItem("Extend (extra monitor)", "extend")
        mode_combo.addItem("Remote (control machine)", "remote")
        current_mode = client_cfg.get("mode", "extend")
        mode_combo.setCurrentIndex(0 if current_mode == "extend" else 1)
        form.addRow("IP Address:", ip)
        form.addRow("Width:", w)
        form.addRow("Height:", h)
        form.addRow("Stream VNC Port:", vnc_port)
        form.addRow("Remote VNC Port:", remote_port)
        form.addRow("Mode:", mode_combo)
        user = QLineEdit(client_cfg.get("user", ""))
        user.setPlaceholderText("macOS username (remote mode only)")
        pw = QLineEdit(client_cfg.get("password", ""))
        pw.setEchoMode(QLineEdit.EchoMode.Password)
        pw.setPlaceholderText("macOS password (remote mode only)")
        form.addRow("Remote User:", user)
        form.addRow("Remote Password:", pw)

        cmd_edit = None
        scmd_edit = None
        if with_command:
            cmd_edit = QPlainTextEdit(client_cfg.get("start_command", ""))
            cmd_edit.setPlaceholderText(
                "Optional shell command to run when this client is online.\n"
                "Variables: {ip} {port} {width} {height} {host_ip}\n"
                "Example: ssh user@{ip} \"tvnviewer -host={host_ip} -port={port} -fullscreen\""
            )
            cmd_edit.setFixedHeight(80)
            scmd_edit = QPlainTextEdit(client_cfg.get("stop_command", ""))
            scmd_edit.setPlaceholderText(
                "Optional shell command to run on teardown.\n"
                "Variables: {ip} {port} {width} {height} {host_ip}\n"
                "Example: ssh user@{ip} \"pkill vncviewer\""
            )
            scmd_edit.setFixedHeight(60)
            form.addRow("Start Command:", cmd_edit)
            form.addRow("Stop Command:", scmd_edit)

        return {"box": box, "ip": ip, "w": w, "h": h,
                "vnc_port": vnc_port, "remote_port": remote_port,
                "mode": mode_combo,
                "user": user, "pw": pw,
                "cmd": cmd_edit, "scmd": scmd_edit}

    def _build_middle_box(self, m_cfg):
        box = CollapsibleGroupBox("Middle (your HDMI monitor)")
        form = QFormLayout(box)
        w = QSpinBox(); w.setRange(640, DP0_MAX_WIDTH); w.setValue(m_cfg["width"])
        h = QSpinBox(); h.setRange(480, 4320); h.setValue(m_cfg["height"])
        form.addRow("Width:", w)
        form.addRow("Height:", h)
        return {"box": box, "w": w, "h": h}

    def _update_total(self):
        total = (self.left_widgets["w"].value()
                 + self.mid_widgets["w"].value()
                 + self.right_widgets["w"].value())
        over = total > DP0_MAX_WIDTH
        color = "#c0392b" if over else "#27ae60"
        status = "EXCEEDS DP-0 LIMIT" if over else "OK"
        self.total_label.setText(
            f"Total width: {total} / {DP0_MAX_WIDTH}   ({status})"
        )
        self.total_label.setStyleSheet(f"font-weight: bold; color: {color};")
        self.save_btn.setEnabled(not over)

    def get_config(self):
        def client(cfg_key, widgets):
            new = dict(self.cfg[cfg_key])
            new.update({
                "ip": widgets["ip"].text().strip(),
                "width": widgets["w"].value(),
                "height": widgets["h"].value(),
                "vnc_port": widgets["vnc_port"].value(),
                "remote_port": widgets["remote_port"].value(),
                "mode": widgets["mode"].currentData(),
                "user": widgets["user"].text().strip(),
                "password": widgets["pw"].text().strip(),
            })
            if widgets["cmd"] is not None:
                new["start_command"] = widgets["cmd"].toPlainText().strip()
                new["stop_command"] = widgets["scmd"].toPlainText().strip()
            return new

        return {
            **self.cfg,
            "host_ip": self.host_ip.text().strip(),
            "left":   client("left", self.left_widgets),
            "right":  client("right", self.right_widgets),
            "middle": {
                **self.cfg["middle"],
                "width": self.mid_widgets["w"].value(),
                "height": self.mid_widgets["h"].value(),
            },
        }


# --------------------------------------------------------------------------
# Tray application
# --------------------------------------------------------------------------
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
        status = QAction(f"Layout: {self.display.layout or 'idle'}", self.menu)
        status.setEnabled(False)
        self.menu.addAction(status)

        ls = "online" if self.left_alive else "offline"
        rs = "online" if self.right_alive else "offline"
        self.menu.addAction(f"  LEFT  ({self.cfg['left']['ip']}): {ls}").setEnabled(False)
        self.menu.addAction(f"  RIGHT ({self.cfg['right']['ip']}): {rs}").setEnabled(False)

        self.menu.addSeparator()

        # --- Mode toggle: LEFT ---
        left_mode = self.cfg["left"].get("mode", "extend")
        a = QAction("LEFT: Remote Control", self.menu)
        a.setCheckable(True)
        a.setChecked(left_mode == "remote")
        a.setEnabled(self.left_alive)
        a.triggered.connect(lambda checked, k="left": self.toggle_mode(k, checked))
        self.menu.addAction(a)

        # --- Mode toggle: RIGHT ---
        right_mode = self.cfg["right"].get("mode", "extend")
        b = QAction("RIGHT: Remote Control", self.menu)
        b.setCheckable(True)
        b.setChecked(right_mode == "remote")
        b.setEnabled(self.right_alive)
        b.triggered.connect(lambda checked, k="right": self.toggle_mode(k, checked))
        self.menu.addAction(b)

        self.menu.addSeparator()

        r = QAction("Restart", self.menu); r.triggered.connect(self.restart); self.menu.addAction(r)
        s = QAction("Stop", self.menu); s.triggered.connect(self.stop); self.menu.addAction(s)
        self.menu.addSeparator()
        sg = QAction("Settings...", self.menu); sg.triggered.connect(self.open_settings); self.menu.addAction(sg)
        vl = QAction("View Logs", self.menu); vl.triggered.connect(self.view_logs); self.menu.addAction(vl)
        q = QAction("Quit", self.menu); q.triggered.connect(self.quit); self.menu.addAction(q)

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
            # Refresh window manager after xrandr changes (xfce4)
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
            try: proc.terminate()
            except Exception: pass
        self.tray.hide()
        self.qapp.quit()


def main():
    log.info("=" * 60)
    log.info("ScreenLink starting")
    log.info("Log file: %s", LOG_PATH)
    log.info("Process logs dir: %s", LOG_DIR)
    log.info("Config file: %s", CONFIG_PATH)
    log.info("=" * 60)

    # Catch any uncaught exception and log it before crashing
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
    main()