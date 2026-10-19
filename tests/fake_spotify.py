"""A fake 'spotify' MPRIS player for testing without Spotify (needs: pip install dbus-next).

    python3 tests/fake_spotify.py            # plays two demo tracks in a loop
Behaves like Spotify: Position is readable but not pushed via PropertiesChanged.
"""

import asyncio
import time

from dbus_next import Variant
from dbus_next.aio import MessageBus
from dbus_next.service import ServiceInterface, dbus_property, method, signal, PropertyAccess

TRACKS = [
    {"id": "/com/spotify/track/demo1", "title": "Everything You Are", "artist": ["Void Test"],
     "album": "Signal Lost", "len": 30_000_000},
    {"id": "/com/spotify/track/demo2", "title": "Unknown Song (Remastered 2011)", "artist": ["Nobody"],
     "album": "Nowhere", "len": 20_000_000},
]


class Root(ServiceInterface):
    def __init__(self):
        super().__init__("org.mpris.MediaPlayer2")

    @dbus_property(access=PropertyAccess.READ)
    def Identity(self) -> "s":
        return "Spotify"


class Player(ServiceInterface):
    def __init__(self):
        super().__init__("org.mpris.MediaPlayer2.Player")
        self.idx = 0
        self.status = "Playing"
        self.pos0 = 0
        self.t0 = time.monotonic()

    def _pos(self):
        if self.status != "Playing":
            return self.pos0
        return int(self.pos0 + (time.monotonic() - self.t0) * 1e6)

    def _md(self):
        t = TRACKS[self.idx]
        return {
            "mpris:trackid": Variant("o", t["id"]),
            "xesam:title": Variant("s", t["title"]),
            "xesam:artist": Variant("as", t["artist"]),
            "xesam:album": Variant("s", t["album"]),
            "mpris:length": Variant("t", t["len"]),
            "mpris:artUrl": Variant("s", ""),
        }

    @dbus_property(access=PropertyAccess.READ)
    def PlaybackStatus(self) -> "s":
        return self.status

    @dbus_property(access=PropertyAccess.READ)
    def Metadata(self) -> "a{sv}":
        return self._md()

    @dbus_property(access=PropertyAccess.READ)
    def Position(self) -> "x":
        return self._pos()

    @dbus_property(access=PropertyAccess.READ)
    def CanSeek(self) -> "b":
        return True

    def _set_status(self, s):
        self.pos0 = self._pos()
        self.t0 = time.monotonic()
        self.status = s
        self.emit_properties_changed({"PlaybackStatus": s})

    @method()
    def PlayPause(self):
        self._set_status("Paused" if self.status == "Playing" else "Playing")

    def change(self, idx):
        self.idx = idx % len(TRACKS)
        self.pos0, self.t0 = 0, time.monotonic()
        self.emit_properties_changed({"Metadata": self._md(), "PlaybackStatus": self.status})

    @method()
    def Next(self):
        self.change(self.idx + 1)

    @method()
    def Previous(self):
        self.change(self.idx - 1)

    @method()
    def Seek(self, offset: "x"):
        self.pos0 = max(0, self._pos() + offset)
        self.t0 = time.monotonic()

    @method()
    def SetPosition(self, track: "o", pos: "x"):
        self.pos0, self.t0 = pos, time.monotonic()

    @signal()
    def Seeked(self, pos) -> "x":
        return pos


async def main():
    bus = await MessageBus().connect()
    p = Player()
    bus.export("/org/mpris/MediaPlayer2", Root())
    bus.export("/org/mpris/MediaPlayer2", p)
    await bus.request_name("org.mpris.MediaPlayer2.spotify")
    while True:
        await asyncio.sleep(0.25)
        if p.status == "Playing" and p._pos() >= TRACKS[p.idx]["len"]:
            p.change(p.idx + 1)


asyncio.run(main())
