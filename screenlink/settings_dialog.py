"""Settings dialog — CollapsibleGroupBox + SettingsDialog."""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QSpinBox, QFormLayout,
    QGroupBox, QPlainTextEdit, QWidget, QComboBox, QScrollArea,
)

from .config import DP0_MAX_WIDTH


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


# --------------------------------------------------------------------------
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
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(self.save_btn)
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
        w = QSpinBox()
        w.setRange(640, DP0_MAX_WIDTH)
        w.setValue(client_cfg["width"])
        h = QSpinBox()
        h.setRange(480, 4320)
        h.setValue(client_cfg["height"])
        vnc_port = QSpinBox()
        vnc_port.setRange(1024, 65535)
        vnc_port.setValue(client_cfg.get("vnc_port", 5900))
        remote_port = QSpinBox()
        remote_port.setRange(1024, 65535)
        remote_port.setValue(client_cfg.get("remote_port", 5900))
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
                'Example: ssh user@{ip} "tvnviewer -host={host_ip} -port={port} -fullscreen"'
            )
            cmd_edit.setFixedHeight(80)
            scmd_edit = QPlainTextEdit(client_cfg.get("stop_command", ""))
            scmd_edit.setPlaceholderText(
                "Optional shell command to run on teardown.\n"
                "Variables: {ip} {port} {width} {height} {host_ip}\n"
                'Example: ssh user@{ip} "pkill vncviewer"'
            )
            scmd_edit.setFixedHeight(60)
            form.addRow("Start Command:", cmd_edit)
            form.addRow("Stop Command:", scmd_edit)

        return {
            "box": box, "ip": ip, "w": w, "h": h,
            "vnc_port": vnc_port, "remote_port": remote_port,
            "mode": mode_combo,
            "user": user, "pw": pw,
            "cmd": cmd_edit, "scmd": scmd_edit,
        }

    def _build_middle_box(self, m_cfg):
        box = CollapsibleGroupBox("Middle (your HDMI monitor)")
        form = QFormLayout(box)
        w = QSpinBox()
        w.setRange(640, DP0_MAX_WIDTH)
        w.setValue(m_cfg["width"])
        h = QSpinBox()
        h.setRange(480, 4320)
        h.setValue(m_cfg["height"])
        form.addRow("Width:", w)
        form.addRow("Height:", h)
        return {"box": box, "w": w, "h": h}

    def _update_total(self):
        total = (
            self.left_widgets["w"].value()
            + self.mid_widgets["w"].value()
            + self.right_widgets["w"].value()
        )
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
            "left": client("left", self.left_widgets),
            "right": client("right", self.right_widgets),
            "middle": {
                **self.cfg["middle"],
                "width": self.mid_widgets["w"].value(),
                "height": self.mid_widgets["h"].value(),
            },
        }
