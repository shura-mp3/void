"""Non-blocking client for void-core's socket, shared by the terminal panes."""

from __future__ import annotations

import json
import select
import socket
import time

from .. import client, paths


class CoreLink:
    def __init__(self, topics: list[str] | None = None, autostart: bool = True):
        self.topics = topics or []
        self.autostart = autostart
        self.sock: socket.socket | None = None
        self.buf = b""
        self._next_try = 0.0
        self._started = False

    @property
    def connected(self) -> bool:
        return self.sock is not None

    def fileno(self) -> int | None:
        return self.sock.fileno() if self.sock else None

    def ensure(self) -> None:
        if self.sock or time.monotonic() < self._next_try:
            return
        self._next_try = time.monotonic() + 2
        s = socket.socket(socket.AF_UNIX)
        try:
            s.connect(str(paths.SOCKET_PATH))
        except OSError:
            s.close()
            if self.autostart and not self._started:
                self._started = True
                client.start_core()
            return
        s.setblocking(False)
        self.sock = s
        self.buf = b""
        if self.topics:
            self.send({"cmd": "sub", "topics": self.topics})

    def send(self, msg: dict) -> None:
        if not self.sock:
            return
        try:
            self.sock.sendall((json.dumps(msg) + "\n").encode())
        except OSError:
            self.close()

    def close(self) -> None:
        if self.sock:
            self.sock.close()
        self.sock = None

    def read(self) -> list[dict]:
        """Drain whatever is available without blocking."""
        if not self.sock:
            return []
        out = []
        while True:
            try:
                chunk = self.sock.recv(65536)
            except BlockingIOError:
                break
            except OSError:
                self.close()
                break
            if not chunk:
                self.close()
                break
            self.buf += chunk
        *lines, self.buf = self.buf.split(b"\n")
        for line in lines:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
        return out

    def wait(self, timeout: float, extra_fds: list[int] | None = None) -> list[int]:
        fds = [f for f in [self.fileno(), *(extra_fds or [])] if f is not None]
        try:
            r, _, _ = select.select(fds, [], [], max(0.0, timeout))
        except InterruptedError:
            return []
        return r
