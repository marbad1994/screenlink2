"""
Display layout management — xrandr, nvidia-settings, VNC servers, viewers.
"""

import os
import subprocess
import shutil

from .config import DP0_MAX_WIDTH
from .helpers import run, ping, render_command
from .logging_setup import log, LOG_DIR


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
