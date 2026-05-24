# ScreenLink

## The Problem Nobody Solved Properly

I run three operating systems — not because I enjoy suffering, but because I need all three. A Linux desktop as my main machine, a Windows laptop, and a MacBook. Each has a role. None of them are going anywhere.

The laptops are both well over ten years old. They sit there with perfectly good screens that are dark most of the day. Meanwhile I'm squinting at one monitor wishing I had more space. I searched for years for a setup that actually worked. Nothing did — not cleanly, not cheaply, not without proprietary hardware or a monthly subscription.

So I built one.

## NVIDIA Said No

The first wall was NVIDIA. They don't support creating virtual displays — no official path, no workaround in the docs. Most people stop there.

I didn't.

Seven days later I had something working. What I learned is that NVIDIA isn't actually the blocker people think it is. You just have to be stubborn enough to find the path they didn't document.

## What ScreenLink Does

ScreenLink turns those unused laptop screens into real extended monitors over LAN using VNC. No new hardware. No paid software. No cloud.

From a tray icon in my toolbar I can set each laptop independently — extend the screen, or switch to remote control. That's it. One decision per machine, instantly.

In practice this means I run one keyboard and one mouse across all three computers. I can have my Linux desktop with two extended screens and one machine remote controlled. Or all three screens extended. Or any combination. My main monitor stays in the center where it belongs and everything else falls into place around it.

## Honest About the Hard Parts

Getting around NVIDIA's limitations while keeping the main monitor centered and everything stable — that was genuinely hard. Frustrating in the way that only good problems are frustrating. The kind where you're cursing at 2am and then something clicks and you feel like you invented electricity.

I use it every single day.

## Why Not Just Buy a Screen?

Part of what drives me is making IT accessible to people who don't have the budget to throw hardware at every problem. Not everyone can just go buy a monitor. But a lot of people have an old laptop collecting dust — and that laptop is an asset waiting to be used.

ScreenLink turns nothing into something. That's the whole point.

**[Read the story here](https://marbad1994.github.io/)**

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
