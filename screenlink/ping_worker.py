"""
Background ping worker — keeps the GUI thread responsive while pinging.
"""

from PyQt6.QtCore import QThread, pyqtSignal

from .helpers import ping
from .logging_setup import log


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
