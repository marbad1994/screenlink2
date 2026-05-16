"""
Logging configuration for ScreenLink.

Writes everything to /tmp/screenlink.log AND stderr.
Process-subprocess captures go to /tmp/screenlink-procs/.
"""

import sys
import logging
from pathlib import Path

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
