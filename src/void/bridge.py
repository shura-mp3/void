"""Loopback WebSocket bridge so Spotify (via the VOID Spicetify theme) becomes a void-core client.

Adapted from Crimson Desktop's bridge; VOID listens on its own port (47812) so the two never collide.

Why WebSocket: Spicetify code runs inside Spotify's renderer and cannot use our unix socket.
Spicetify's own built-in `webnowplaying.js` extension talks to ws://localhost, so a loopback
WebSocket is the established mechanism. Implemented with the standard library only.

Security model
  * binds 127.0.0.1 only (never a public interface)
  * the Origin header must be in an allow-list (default: Spotify's UI origin
    https://xpui.app.spotify.com), so ordinary web pages in a browser are refused
  * clients may only subscribe to topics and nudge the per-track lyric offset; playback
    control stays inside Spotify itself (Spicetify.Player), so there is one controller
  * frame / handshake sizes are capped
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import struct

log = logging.getLogger("void.bridge")

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
BRIDGE_TOPICS = {"player", "lyrics", "ui", "toast", "spec"}  # never sys
BRIDGE_COMMANDS = {"sub", "offset", "ping"}
MAX_FRAME = 4096
MAX_HANDSHAKE = 8192


def accept_key(key: str) -> str:
    return base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()


def encode_text(payload: str) -> bytes:
    data = payload.encode()
    n = len(data)
    if n < 126:
        head = struct.pack("!BB", 0x81, n)
    elif n < 65536:
        head = struct.pack("!BBH", 0x81, 126, n)
    else:
        head = struct.pack("!BBQ", 0x81, 127, n)
    return head + data


def encode_control(opcode: int, payload: bytes = b"") -> bytes:
    return struct.pack("!BB", 0x80 | opcode, len(payload)) + payload


async def read_frame(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    b1, b2 = await reader.readexactly(2)
    fin, opcode, masked, n = b1 & 0x80, b1 & 0x0F, b2 & 0x80, b2 & 0x7F
    if not masked:
        raise ConnectionError("client frames must be masked")
    if n == 126:
        (n,) = struct.unpack("!H", await reader.readexactly(2))
    elif n == 127:
        (n,) = struct.unpack("!Q", await reader.readexactly(8))
    if n > MAX_FRAME or not fin:
        raise ConnectionError("frame too large or fragmented")
    mask = await reader.readexactly(4)
    data = bytearray(await reader.readexactly(n))
    for i in range(n):
        data[i] ^= mask[i % 4]
    return opcode, bytes(data)


class Bridge:
    def __init__(self, core, cfg: dict):
        self.core = core
        self.host = "127.0.0.1"
        self.port = int(cfg.get("bridge_port", 47812))
        self.origins = set(cfg.get("allowed_origins", ["https://xpui.app.spotify.com"]))
        self.server: asyncio.AbstractServer | None = None
        self.last_rejected_origin: str | None = None
        self.connections = 0

    async def start(self) -> None:
        try:
            self.server = await asyncio.start_server(self._handle, self.host, self.port)
            log.info("spicetify bridge on ws://%s:%d", self.host, self.port)
        except OSError as e:
            log.error("spicetify bridge could not bind %s:%d (%s) - Spotify integration disabled", self.host, self.port, e)

    async def _handshake(self, reader, writer) -> bool:
        raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
        if len(raw) > MAX_HANDSHAKE:
            return False
        lines = raw.decode("latin-1").split("\r\n")
        if not lines[0].startswith("GET "):
            return False
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        origin = headers.get("origin", "")
        if origin not in self.origins:
            self.last_rejected_origin = origin or "(none)"
            log.warning("bridge: refused connection from origin %r (allowed: %s)", origin, sorted(self.origins))
            writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            return False
        if headers.get("upgrade", "").lower() != "websocket" or "sec-websocket-key" not in headers:
            writer.write(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            return False
        writer.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                      f"Sec-WebSocket-Accept: {accept_key(headers['sec-websocket-key'])}\r\n\r\n").encode())
        await writer.drain()
        return True

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        from .core import Client  # local import: core imports this module
        client = None
        try:
            if not await self._handshake(reader, writer):
                return

            def send(data: bytes) -> None:
                if writer.transport.get_write_buffer_size() > 1_000_000:
                    raise ConnectionError("bridge client too slow")
                writer.write(encode_text(data.decode().rstrip("\n")))

            client = Client(send, topics=())
            self.connections += 1
            self.core.clients.add(client)
            self.core.snapshot(client)
            while True:
                opcode, payload = await read_frame(reader)
                if opcode == 0x8:  # close
                    writer.write(encode_control(0x8))
                    break
                if opcode == 0x9:  # ping
                    writer.write(encode_control(0xA, payload[:125]))
                    continue
                if opcode != 0x1:
                    continue
                try:
                    msg = json.loads(payload)
                except ValueError:
                    continue
                if not isinstance(msg, dict) or msg.get("cmd") not in BRIDGE_COMMANDS:
                    continue
                if msg["cmd"] == "sub":
                    topics = [t for t in msg.get("topics", []) if t in BRIDGE_TOPICS]
                    msg = {"cmd": "sub", "topics": topics}
                elif msg["cmd"] == "offset":
                    delta = msg.get("delta", 0)
                    msg = {"cmd": "offset", "reset": bool(msg.get("reset")),
                           "delta": max(-2000, min(2000, int(delta))) if isinstance(delta, (int, float)) else 0}
                reply = await self.core.command(client, msg)
                if reply is not None and msg.get("cmd") != "sub":
                    writer.write(encode_text(json.dumps({"t": "reply", **reply})))
        except (asyncio.IncompleteReadError, ConnectionError, asyncio.TimeoutError, asyncio.LimitOverrunError, ValueError):
            pass
        finally:
            if client is not None:
                self.core.clients.discard(client)
                self.connections -= 1
                self.core._update_audio()
            writer.close()
