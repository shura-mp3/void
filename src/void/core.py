"""void-core: the single shared backend (adapted from Crimson Desktop's crimson-core).

Owns the MPRIS watcher, lyrics lookup, album-art cache, CAVA, system stats and the performance
profile, and streams newline-delimited JSON over a Unix socket
($XDG_RUNTIME_DIR/void-desktop/core.sock) to any number of clients: the dashboard's music pane,
the Konsole `void music` view, the Spotify theme (through the loopback bridge) and `void` commands.
VOID and Crimson are never both running: activation pauses crimson-core, so Spotify is watched
and lyrics are fetched by exactly one process.

Clients extrapolate playback position themselves from (pos_ms, mono) anchors, so the socket
only carries events, not a 60 Hz position stream.
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import hashlib
import json
import logging
import os
import signal
import socket
import time
import urllib.request
from pathlib import Path
from typing import Callable

from . import __version__, config, paths
from .audio import Spectrum
from .lyrics import LyricsService, norm, USER_AGENT
from .mpris import MprisWatcher, PlayerState
from .sysinfo import SysInfo

log = logging.getLogger("void.core")

ALWAYS = {"player", "lyrics", "art", "ui", "toast"}


class Client:
    def __init__(self, send: Callable[[bytes], None], topics=None, close=None):
        self.send = send
        self.topics = set(topics or ()) | ALWAYS
        self.close = close


class Core:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.clients: set[Client] = set()
        self.mpris = MprisWatcher(cfg, self._on_player)
        self.lyrics_svc = LyricsService(cfg)
        self.spectrum = Spectrum(cfg, self._on_spectrum, lambda: self._broadcast("ui", self.ui_msg()))
        self.sys = SysInfo()
        self.offsets = config.JsonState(paths.OFFSETS_FILE)
        self.ui = config.JsonState(paths.UI_STATE_FILE, {
            "performance": cfg["dashboard"].get("performance", "balanced"),
        })
        self.gamemode = False
        self.overloaded = False
        self.lyrics: dict = {"status": "none", "lines": [], "track_id": ""}
        self.art_path = ""
        self._track_key = ""
        self._lyrics_task: asyncio.Task | None = None
        self._art_task: asyncio.Task | None = None
        self._audio_stop_handle: asyncio.TimerHandle | None = None
        self._last_sys: dict = {}
        self.loop: asyncio.AbstractEventLoop | None = None
        self.bridge = None

    # ------------------------------------------------------------------ messaging
    def _broadcast(self, topic: str, msg: dict) -> None:
        data = (json.dumps({"t": topic, **msg}, separators=(",", ":")) + "\n").encode()
        for c in list(self.clients):
            if topic in c.topics:
                try:
                    c.send(data)
                except Exception:  # noqa: BLE001 - a broken client must never break the core
                    self.clients.discard(c)

    def snapshot(self, client: Client) -> None:
        for topic, msg in (("ui", self.ui_msg()), ("player", self.player_msg()),
                           ("lyrics", self.lyrics_msg()), ("art", self.art_msg())):
            client.send((json.dumps({"t": topic, **msg}) + "\n").encode())
        if "sys" in client.topics and self._last_sys:
            client.send((json.dumps({"t": "sys", **self._last_sys}) + "\n").encode())

    def player_msg(self) -> dict:
        st = self.mpris.state
        d = st.to_dict()
        d["pos_ms"] = st.position()
        d["mono"] = time.monotonic()
        d.pop("anchor", None)
        return d

    def lyrics_msg(self) -> dict:
        return {**self.lyrics, "offset_ms": self.total_offset(), "user_offset_ms": self.user_offset()}

    def art_msg(self) -> dict:
        return {"track_id": self.mpris.state.track.id, "path": self.art_path}

    def ui_msg(self) -> dict:
        perf = self.effective_performance()
        return {
            **self.ui.data,
            "effective_performance": perf,
            "perf": config.PERFORMANCE[perf],
            "grayscale_art": bool(self.cfg["spicetify"].get("grayscale_art", False)),
            "gamemode": self.gamemode,
            "overloaded": self.overloaded,
            "audio_available": self.spectrum.available,
            "audio_source": self.spectrum.active_source,
            "audio_error": self.spectrum.error,
            "version": __version__,
        }

    def toast(self, text: str) -> None:
        self._broadcast("toast", {"text": text})

    # ------------------------------------------------------------------ performance / ui
    def effective_performance(self) -> str:
        perf = self.ui.data.get("performance", "balanced")
        if perf not in config.PERFORMANCE:
            perf = "balanced"
        if (self.gamemode and self.cfg["dashboard"].get("gamemode_action", "minimal") == "minimal") or self.overloaded:
            return "minimal"
        return perf

    def _ui_changed(self) -> None:
        self.ui.save()
        self._broadcast("ui", self.ui_msg())
        self._update_audio()

    # ------------------------------------------------------------------ player events
    def _key(self, st: PlayerState) -> str:
        return st.track.id or f"{norm(st.track.artist)}|{norm(st.track.title)}"

    def user_offset(self) -> int:
        return int(self.offsets.data.get(self._track_key, 0))

    def total_offset(self) -> int:
        return int(self.cfg["lyrics"].get("latency_ms", 0)) + int(self.lyrics.get("lrc_offset", 0)) + self.user_offset()

    def _on_player(self, reason: str, st: PlayerState) -> None:
        key = self._key(st) if st.track.title else ""
        if key != self._track_key:
            self._track_key = key
            self._start_track_tasks(st)
        elif reason == "meta" and st.track.art_url and not self.art_path:
            self._start_art(st)
        self._broadcast("player", self.player_msg())
        self._update_audio()

    def _start_track_tasks(self, st: PlayerState) -> None:
        for t in (self._lyrics_task, self._art_task):
            if t and not t.done():
                t.cancel()
        self.art_path = ""
        tid = st.track.id
        if not st.track.title:
            self.lyrics = {"status": "none", "lines": [], "track_id": ""}
            self._broadcast("lyrics", self.lyrics_msg())
            self._broadcast("art", self.art_msg())
            return
        if st.track.is_ad:
            self.lyrics = {"status": "ad", "lines": [], "track_id": tid}
            self._broadcast("lyrics", self.lyrics_msg())
        else:
            self._lyrics_task = asyncio.create_task(self._load_lyrics(st.track))
        self._start_art(st)

    def _start_art(self, st: PlayerState) -> None:
        if st.track.art_url:
            self._art_task = asyncio.create_task(self._load_art(st.track.id, st.track.art_url))
        else:
            self._broadcast("art", self.art_msg())

    RETRY_DELAYS = (15, 60, 180)  # seconds; network errors are retried while the same track plays

    async def _load_lyrics(self, track, force: bool = False) -> None:
        self.lyrics = {"status": "loading", "lines": [], "track_id": track.id}
        self._broadcast("lyrics", self.lyrics_msg())
        for attempt in range(len(self.RETRY_DELAYS) + 1):
            res = await asyncio.get_running_loop().run_in_executor(
                None, self.lyrics_svc.lookup, track.artist, track.title, track.album, track.length_ms, force)
            if track.id != self.mpris.state.track.id:
                return  # track changed while we were fetching (this task is cancelled on track change too)
            retry_in = self.RETRY_DELAYS[attempt] if res["status"] == "error" and attempt < len(self.RETRY_DELAYS) else 0
            self.lyrics = {**res, "track_id": track.id, "retry_in": retry_in,
                           "error": res.get("source", "").removeprefix("network: ") if res["status"] == "error" else ""}
            log.info("lyrics for %s - %s: %s (%s)%s", track.artist, track.title, res["status"], res.get("source"),
                     f" - retrying in {retry_in}s" if retry_in else "")
            self._broadcast("lyrics", self.lyrics_msg())
            if not retry_in:
                return
            await asyncio.sleep(retry_in)

    async def _load_art(self, track_id: str, url: str) -> None:
        def fetch() -> str:
            if url.startswith("file://"):
                return url[7:]
            dest = paths.ART_CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".img")
            if not dest.exists():
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=8) as r:
                    data = r.read(8 * 1024 * 1024)
                tmp = dest.with_suffix(".tmp")
                tmp.write_bytes(data)
                tmp.replace(dest)
                self._prune_art()
            return str(dest)

        try:
            path = await asyncio.get_running_loop().run_in_executor(None, fetch)
        except Exception as e:  # noqa: BLE001
            log.warning("album art download failed: %s", e)
            path = ""
        if track_id == self.mpris.state.track.id:
            self.art_path = path
            self._broadcast("art", self.art_msg())

    @staticmethod
    def _prune_art(keep: int = 300) -> None:
        files = sorted(paths.ART_CACHE.glob("*.img"), key=lambda p: p.stat().st_mtime)
        for p in files[:-keep]:
            p.unlink(missing_ok=True)

    # ------------------------------------------------------------------ audio
    def _on_spectrum(self, bars: list[int]) -> None:
        self._broadcast("spec", {"b": bars})

    def _wants_audio(self) -> bool:
        return (self.mpris.state.playing and config.PERFORMANCE[self.effective_performance()]["spectrum"]
                and any("spec" in c.topics for c in self.clients))

    def _update_audio(self) -> None:
        if self._wants_audio():
            if self._audio_stop_handle:
                self._audio_stop_handle.cancel()
                self._audio_stop_handle = None
            fps = config.PERFORMANCE[self.effective_performance()]["cava_fps"]
            asyncio.ensure_future(self.spectrum.start(fps))
        elif self.spectrum.running and not self._audio_stop_handle:
            # short grace period so quick pause/skip doesn't restart cava
            self._audio_stop_handle = self.loop.call_later(2.5, self._stop_audio)

    def _stop_audio(self) -> None:
        self._audio_stop_handle = None
        if not self._wants_audio():
            asyncio.ensure_future(self.spectrum.stop())
            self._broadcast("spec", {"b": [0] * self.spectrum.bars})

    # ------------------------------------------------------------------ background loops
    async def _gamemode_active(self) -> bool:
        router = self.mpris.router
        if not router:
            return False
        try:
            from jeepney import DBusAddress, MessageType, Properties
            addr = DBusAddress("/com/feralinteractive/GameMode", bus_name="com.feralinteractive.GameMode",
                               interface="com.feralinteractive.GameMode")
            reply = await asyncio.wait_for(router.send_and_get_reply(Properties(addr).get("ClientCount")), 1)
            if reply.header.message_type == MessageType.error:
                return False
            return int(reply.body[0][1]) > 0
        except Exception:  # noqa: BLE001 - gamemoded not installed / not running
            return False

    async def _sys_loop(self) -> None:
        asyncio.create_task(self.sys.load_static())
        cores = os.cpu_count() or 1
        while True:
            want = any("sys" in c.topics for c in self.clients)
            try:
                sample = await self.sys.sample()
                self._last_sys = sample
                if want:
                    self._broadcast("sys", sample)
                gm = await self._gamemode_active()
                over = sample["load"][0] > cores * float(self.cfg["dashboard"].get("load_threshold", 0.9))
                if gm != self.gamemode or over != self.overloaded:
                    if gm != self.gamemode:
                        self.toast("GAMEMODE ACTIVE // MINIMAL PROFILE" if gm else "GAMEMODE OFF")
                    self.gamemode, self.overloaded = gm, over
                    self._broadcast("ui", self.ui_msg())
                    self._update_audio()
            except Exception as e:  # noqa: BLE001
                log.debug("sys sample failed: %s", e)
            await asyncio.sleep(2 if want else 6)

    # ------------------------------------------------------------------ commands
    async def command(self, client: Client | None, msg: dict) -> dict | None:
        cmd = msg.get("cmd")
        if cmd not in ("sub", "status", "ping"):
            log.info("command %s", {k: v for k, v in msg.items() if k != "id"})
        m = self.mpris
        if cmd == "sub":
            if client:
                client.topics = set(msg.get("topics", [])) | ALWAYS
                self._update_audio()
            return None
        if cmd == "play_pause":
            await m.play_pause()
        elif cmd == "next":
            await m.next()
        elif cmd in ("prev", "previous"):
            await m.previous()
        elif cmd == "raise":
            await m.raise_window()
        elif cmd == "seek":
            await m.set_position(int(msg.get("ms", 0)))
        elif cmd == "seek_rel":
            await m.seek_relative(int(msg.get("ms", 0)))
        elif cmd == "offset":
            if not self._track_key:
                return {"ok": False, "error": "no track"}
            if msg.get("reset"):
                self.offsets.data.pop(self._track_key, None)
            else:
                self.offsets.data[self._track_key] = self.user_offset() + int(msg.get("delta", 0))
            self.offsets.save()
            self._broadcast("lyrics", self.lyrics_msg())
            self.toast(f"LYRIC OFFSET {self.user_offset():+d} MS")
            return {"ok": True, "offset_ms": self.user_offset()}
        elif cmd == "reload_lyrics":
            st = m.state
            if st.track.title:
                self.lyrics_svc.forget(st.track.artist, st.track.title, st.track.length_ms)
                self._lyrics_task = asyncio.create_task(self._load_lyrics(st.track, force=True))
        elif cmd == "ui":
            perf = msg.get("performance")
            if perf is not None:
                if perf not in config.PERFORMANCE:
                    return {"ok": False, "error": f"unknown profile {perf!r} (minimal | balanced | showcase)"}
                self.ui.data["performance"] = perf
            self._ui_changed()
        elif cmd == "status":
            st = m.state
            return {
                "ok": True, "version": __version__, "player": st.to_dict(), "position_ms": st.position(),
                "lyrics_status": self.lyrics.get("status"), "lyrics_source": self.lyrics.get("source"),
                "offset_ms": self.total_offset(), "ui": self.ui_msg(), "clients": len(self.clients),
                "audio_running": self.spectrum.running,
                "bridge": None if not self.bridge else {
                    "port": self.bridge.port, "listening": self.bridge.server is not None,
                    "connections": self.bridge.connections, "last_rejected_origin": self.bridge.last_rejected_origin},
            }
        elif cmd == "ping":
            pass
        else:
            return {"ok": False, "error": f"unknown command {cmd!r}"}
        return {"ok": True}

    # ------------------------------------------------------------------ socket server
    async def _serve_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        def send(data: bytes) -> None:
            if writer.transport.get_write_buffer_size() > 1_000_000:
                raise ConnectionError("client too slow")
            writer.write(data)

        client = Client(send)
        self.clients.add(client)
        try:
            self.snapshot(client)
            while line := await reader.readline():
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                reply = await self.command(client, msg)
                if reply is not None and msg.get("id") is not None:
                    send((json.dumps({"t": "reply", "id": msg["id"], **reply}) + "\n").encode())
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            self.clients.discard(client)
            self._update_audio()
            writer.close()

    def add_local_client(self, on_message: Callable[[dict], None], topics=()) -> Client:
        """In-process client (used by the TUI when no core service is running)."""
        c = Client(lambda data: on_message(json.loads(data)), topics)
        self.clients.add(c)
        self.snapshot(c)
        return c

    async def start(self, serve: bool = True) -> None:
        self.loop = asyncio.get_running_loop()
        paths.ensure_dirs()
        if serve:
            await self._bind()
        asyncio.create_task(self.mpris.run())
        asyncio.create_task(self._sys_loop())
        if serve and self.cfg.get("spicetify", {}).get("bridge", True):
            from .bridge import Bridge
            self.bridge = Bridge(self, self.cfg["spicetify"])
            await self.bridge.start()

    async def _bind(self) -> None:
        sock_path = paths.SOCKET_PATH
        if sock_path.exists():
            probe = socket.socket(socket.AF_UNIX)
            try:
                probe.connect(str(sock_path))
                raise SystemExit("void-core is already running")
            except (ConnectionRefusedError, FileNotFoundError):
                sock_path.unlink(missing_ok=True)
            finally:
                probe.close()
        self.server = await asyncio.start_unix_server(self._serve_client, path=str(sock_path))
        os.chmod(sock_path, 0o600)
        log.info("listening on %s", sock_path)


def _single_instance_lock() -> object:
    paths.ensure_dirs()
    f = open(paths.RUNTIME_DIR / "core.lock", "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("void-core is already running")
    return f


async def amain(args) -> None:
    cfg = config.load(Path(args.config) if args.config else None)
    core = Core(cfg)
    await core.start()
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    await stop.wait()
    # backstop: never let a stuck thread or library keep a stopped service alive
    import threading
    watchdog = threading.Timer(5, os._exit, args=(0,))
    watchdog.daemon = True  # must not itself delay a normal exit
    watchdog.start()
    await core.spectrum.stop()
    paths.SOCKET_PATH.unlink(missing_ok=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="VOID shared backend (void-core)")
    ap.add_argument("--config")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    lock = _single_instance_lock()  # noqa: F841 - held for the life of the process
    asyncio.run(amain(args))


if __name__ == "__main__":
    main()
