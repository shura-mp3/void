"""Real audio spectrum via CAVA (raw 8-bit binary output on stdout).

Source modes:
  system  - CAVA's PipeWire input with source=auto: the monitor of your default output, i.e.
            everything you hear (Spotify, browser, games...). This is the reliable default.
  spotify - experimental: we look up Spotify's playback stream with `pw-dump` and point CAVA's
            PipeWire input at that node, so only Spotify drives the visualiser. Recording from an
            application stream does not interrupt its playback, but it depends on PipeWire /
            WirePlumber versions; if the node can't be found we fall back to `system`.

CAVA only runs while something subscribes to the spectrum AND music is playing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from typing import Callable

from . import paths

log = logging.getLogger(__name__)

CAVA_TEMPLATE = """\
[general]
framerate = {fps}
autosens = 1
bars = {bars}
lower_cutoff_freq = 40
higher_cutoff_freq = 12000
sleep_timer = 0

[input]
method = {method}
source = {source}

[output]
method = raw
raw_target = /dev/stdout
data_format = binary
bit_format = 8bit
channels = mono
mono_option = average

[smoothing]
noise_reduction = 70
monstercat = 0
"""


async def find_spotify_node() -> str | None:
    """object.serial of Spotify's output stream, via pw-dump. None if not found."""
    if not shutil.which("pw-dump"):
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            "pw-dump", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(proc.communicate(), 5)
        for obj in json.loads(out or b"[]"):
            if obj.get("type") != "PipeWire:Interface:Node":
                continue
            props = (obj.get("info") or {}).get("props") or {}
            if props.get("media.class") != "Stream/Output/Audio":
                continue
            names = " ".join(str(props.get(k, "")) for k in
                             ("application.name", "application.process.binary", "node.name")).lower()
            if "spotify" in names:
                return str(props.get("object.serial") or obj.get("id"))
    except (OSError, ValueError, asyncio.TimeoutError) as e:
        log.debug("pw-dump failed: %s", e)
    return None


class Spectrum:
    def __init__(self, cfg: dict, on_frame: Callable[[list[int]], None], on_state: Callable[[], None] = lambda: None):
        self.cfg = cfg["audio"]
        self.on_frame = on_frame
        self.on_state = on_state  # called when running/source/error changes
        self.proc: asyncio.subprocess.Process | None = None
        self.task: asyncio.Task | None = None
        self.bars = int(self.cfg.get("bars", 48))
        self.fps = 45
        # advanced: [audio] input_method = "pulse" | "fifo" (testing) ; default PipeWire
        self.method = self.cfg.get("input_method", "pipewire")
        self.active_source = "system"
        self.error: str | None = None

    @property
    def available(self) -> bool:
        return bool(self.cfg.get("enabled", True) and shutil.which(self.cfg.get("cava_binary", "cava")))

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    async def start(self, fps: int) -> None:
        if self.running and fps == self.fps:
            return
        await self.stop()
        if not self.available:
            self.error = "cava not installed"
            return
        self.fps = fps
        source = self.cfg.get("input_source", "auto")
        self.active_source = "system" if source == "auto" else source
        if self.cfg.get("source") == "spotify" and self.method == "pipewire":
            node = await find_spotify_node()
            if node:
                source, self.active_source = node, "spotify"
            else:
                log.info("Spotify PipeWire stream not found; visualiser uses system audio")
        conf = paths.RUNTIME_DIR / "cava.conf"
        conf.write_text(CAVA_TEMPLATE.format(fps=fps, bars=self.bars, method=self.method, source=source))
        # stderr goes to a file: an unread pipe could fill up and stall cava
        self._errlog = paths.RUNTIME_DIR / "cava.log"
        with open(self._errlog, "wb") as errf:
            self.proc = await asyncio.create_subprocess_exec(
                self.cfg.get("cava_binary", "cava"), "-p", str(conf),
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=errf)
        self.task = asyncio.create_task(self._read(self.proc))
        self.error = None
        self.on_state()
        log.info("cava started (%s, %d bars @ %d fps, source=%s)", self.method, self.bars, fps, self.active_source)

    async def _read(self, proc) -> None:
        got_frame = False
        try:
            while True:
                data = await proc.stdout.readexactly(self.bars)
                got_frame = True
                self.on_frame(list(data))
        except (asyncio.IncompleteReadError, asyncio.CancelledError):
            pass
        finally:
            if proc.returncode is None:
                try:
                    await asyncio.wait_for(proc.wait(), 0.2)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass
            if not got_frame and proc.returncode not in (None, 0, -15):
                try:
                    err = self._errlog.read_text(errors="replace").strip()
                except OSError:
                    err = ""
                self.error = err[-300:] or f"cava exited with {proc.returncode}"
                log.warning("cava failed: %s", self.error)
                self.on_state()
                if self.method == "pipewire":
                    # cava built without PipeWire support: fall back to PulseAudio (pipewire-pulse)
                    log.info("retrying cava with the pulse input method")
                    self.method = "pulse"
                    asyncio.get_running_loop().call_soon(lambda: asyncio.ensure_future(self.start(self.fps)))

    async def stop(self) -> None:
        if self.proc and self.proc.returncode is None:
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), 2)
            except asyncio.TimeoutError:
                self.proc.kill()
        if self.task:
            self.task.cancel()
        self.proc = self.task = None
