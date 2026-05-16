"""
System helpers — subprocess runner, ping, template rendering.
"""

import subprocess
from .logging_setup import log


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
