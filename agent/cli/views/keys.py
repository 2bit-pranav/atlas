"""Reading single keys from the console while the start screen is up."""


from __future__ import annotations

import queue
import sys
import threading
from typing import Any


class _Keys:
    """Single key presses without Enter, on Windows and POSIX terminals."""

    def __init__(self) -> None:
        self.queue: queue.Queue[str] = queue.Queue()
        self._stop = threading.Event()
        self._restore: Any = None

    def start(self) -> None:
        if sys.platform != "win32":
            import termios
            import tty

            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            tty.setcbreak(fd)  # keeps ISIG, so Ctrl+C still interrupts
            self._restore = lambda: termios.tcsetattr(fd, termios.TCSADRAIN, old)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        if sys.platform == "win32":
            import msvcrt

            while not self._stop.wait(0.05):
                while msvcrt.kbhit():
                    ch = msvcrt.getwch()
                    if ch in ("\x00", "\xe0"):  # arrows and function keys: two codes
                        code = msvcrt.getwch()
                        ch = {"K": "left", "M": "right"}.get(code, "")
                    self.queue.put({"\t": "right", "\x1b": "esc", "\x03": "q"}.get(ch, ch.lower()))
        else:
            import select

            while not self._stop.is_set():
                ready, _, _ = select.select([sys.stdin], [], [], 0.1)
                if ready:
                    ch = sys.stdin.read(1)
                    if ch == "\x1b":  # Esc, or the start of an arrow key
                        more, _, _ = select.select([sys.stdin], [], [], 0.02)
                        if more and sys.stdin.read(1) == "[":
                            ch = {"D": "left", "C": "right"}.get(sys.stdin.read(1), "")
                        else:
                            ch = "esc"
                    self.queue.put({"\t": "right"}.get(ch, ch.lower()))

    def stop(self) -> None:
        self._stop.set()
        if self._restore:
            self._restore()


__all__ = []
