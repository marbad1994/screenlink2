# ScreenLink

Dynamic multi-display orchestration with system tray integration.

Automatically detects online clients (via ping), configures the display
layout across 1–3 screens, and manages VNC remote sessions — all from a
small tray icon.

## Features

- **Auto-layout** — detects left/right clients at startup and arranges
  screens accordingly (single / dual / triple)
- **Remote Control** — toggle any client between *extend* (extra monitor)
  and *remote* (control the remote desktop) from the tray menu
- **Per-client commands** — configurable start/stop commands support
  template variables for SSH + VNC automation
- **NVIDIA-aware** — uses `nvidia-settings` to enforce DP-0 width limit
  (5120 px), then fine-tunes with `xrandr`
- **System tray** — menu shows online/offline status, quick restart,
  settings, and log viewer

## Requirements

- Linux with X11 (Xfce recommended)
- Python 3.10+
- PyQt6
- `nvidia-settings` (NVIDIA GPU)
- `xrandr`
- `vncviewer` and/or `x0vncserver` (depending on modes)

## Install

### From binary (pre-built)

```bash
sudo cp dist/screenlink /usr/local/bin/screenlink
screenlink          # daemonizes — watch logs with:
tail -f /tmp/screenlink.log
```

### From source

```bash
pip install --user pyinstaller PyQt6
pyinstaller --onefile --name screenlink --noconsole --noupx screenlink.py
sudo cp dist/screenlink /usr/local/bin/screenlink
```

### Autostart (Xfce)

Add *ScreenLink* to **Session and Startup** → *Application Autostart*:

```
Name:    ScreenLink
Command: /usr/local/bin/screenlink
```

## Configuration

First run creates `~/.config/screenlink/config.json` with defaults.
Edit it to set your client IPs, resolutions, and launch commands.

Template variables available in `start_command` / `stop_command`:
`{ip}`, `{port}`, `{width}`, `{height}`, `{host_ip}`

## Logs

| Log | Path |
|---|---|
| Main log | `/tmp/screenlink.log` |
| Per-process logs | `/tmp/screenlink-procs/` |

```bash
tail -f /tmp/screenlink.log
```

## Build

```bash
pip install pyinstaller PyQt6
pyinstaller --onefile --name screenlink --noconsole --noupx screenlink.py
# Output: dist/screenlink
```

## License

MIT
