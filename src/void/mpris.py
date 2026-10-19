"""Event-driven MPRIS (D-Bus) watcher for the native Spotify client.

What MPRIS gives us: title / artist / album / art URL / length / playback status, change
signals, and a Position *property* (not pushed via PropertiesChanged). It does NOT give lyrics
or sample-accurate timing. So position is modelled as an anchor (pos, monotonic time, rate) that
is extrapolated locally and corrected by:
  * PlaybackStatus / Metadata changes (re-read Position immediately, then again shortly after,
    because Spotify sometimes reports the previous track's position for a moment)
  * the Seeked signal (if the player emits it)
  * a light periodic re-read while playing (default every 1.5 s) to catch seeks and drift.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field, asdict
from typing import Callable

from jeepney import DBusAddress, HeaderFields, MessageType, Properties, new_method_call
from jeepney.bus_messages import DBus, MatchRule
from jeepney.io.asyncio import open_dbus_router
from jeepney.wrappers import DBusErrorResponse

log = logging.getLogger(__name__)

MPRIS_PATH = "/org/mpris/MediaPlayer2"
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"
PREFIX = "org.mpris.MediaPlayer2."


def _unwrap(v):
    # jeepney returns variants as (signature, value)
    if isinstance(v, tuple) and len(v) == 2 and isinstance(v[0], str):
        return v[1]
    return v


@dataclass
class Track:
    id: str = ""
    title: str = ""
    artist: str = ""
    album: str = ""
    art_url: str = ""
    length_ms: int = 0
    url: str = ""

    @property
    def is_ad(self) -> bool:
        return self.id.startswith(("spotify:ad:", "/com/spotify/ad/")) or ":ad:" in self.id

    @classmethod
    def from_metadata(cls, md: dict) -> "Track":
        md = {k: _unwrap(v) for k, v in (md or {}).items()}
        artist = md.get("xesam:artist") or md.get("xesam:albumArtist") or []
        if isinstance(artist, str):
            artist = [artist]
        art = md.get("mpris:artUrl") or ""
        # Older Spotify builds report open.spotify.com/image/<id>; the image itself lives on i.scdn.co.
        if art.startswith("https://open.spotify.com/image/"):
            art = "https://i.scdn.co/image/" + art.rsplit("/", 1)[-1]
        length = md.get("mpris:length") or 0
        return cls(
            id=str(md.get("mpris:trackid") or md.get("xesam:url") or ""),
            title=md.get("xesam:title") or "",
            artist=", ".join(a for a in artist if a),
            album=md.get("xesam:album") or "",
            art_url=art,
            length_ms=int(length) // 1000 if length else 0,
            url=md.get("xesam:url") or "",
        )


@dataclass
class PlayerState:
    available: bool = False
    player: str = ""
    status: str = "Stopped"  # Playing | Paused | Stopped
    track: Track = field(default_factory=Track)
    pos_ms: float = 0.0  # position at anchor
    anchor: float = 0.0  # time.monotonic() at anchor
    can_seek: bool = True

    @property
    def playing(self) -> bool:
        return self.status == "Playing"

    def position(self) -> float:
        if not self.playing:
            return self.pos_ms
        p = self.pos_ms + (time.monotonic() - self.anchor) * 1000
        return min(p, self.track.length_ms) if self.track.length_ms else p

    def to_dict(self) -> dict:
        d = asdict(self)
        d["playing"] = self.playing
        d["is_ad"] = self.track.is_ad
        return d


class MprisWatcher:
    def __init__(self, cfg: dict, on_change: Callable[[str, PlayerState], None]):
        self.players = cfg["spotify"].get("players", ["spotify"])
        self.resync_interval = float(cfg["spotify"].get("resync_interval", 1.5))
        self.on_change = on_change  # (reason, state); reason in {"player","track","status","position"}
        self.state = PlayerState()
        self.router = None
        self.bus_name: str | None = None  # well-known name we follow
        self.owner: str | None = None  # its unique name
        self._owners: dict[str, str] = {}  # well-known -> unique, for every MPRIS player seen
        self._zero_pos_since: float | None = None

    # ---------------- lifecycle ----------------
    async def run(self) -> None:
        while True:
            try:
                async with open_dbus_router(bus="SESSION") as router:
                    self.router = router
                    await self._main(router)
            except Exception as e:  # noqa: BLE001 - EOFError/RouterClosed/OSError: bus went away
                task = asyncio.current_task()
                if task is not None and task.cancelling():
                    # jeepney's __aexit__ can replace our CancelledError with EOFError on a dead
                    # connection; swallowing it would make shutdown hang forever
                    raise asyncio.CancelledError from e
                log.error("session bus connection lost (%r); retrying in 3s", e)
            finally:
                self.router = None
            self._set_unavailable()
            await asyncio.sleep(3)

    async def _main(self, router) -> None:
        dbus = DBus()
        rules = [
            MatchRule(type="signal", sender="org.freedesktop.DBus", interface="org.freedesktop.DBus",
                      member="NameOwnerChanged", path="/org/freedesktop/DBus"),
            MatchRule(type="signal", interface="org.freedesktop.DBus.Properties", member="PropertiesChanged",
                      path=MPRIS_PATH),
            MatchRule(type="signal", interface=PLAYER_IFACE, member="Seeked", path=MPRIS_PATH),
        ]
        queue: asyncio.Queue = asyncio.Queue()
        handles = [router.filter(r, queue=queue) for r in rules]
        for r in rules:
            await router.send_and_get_reply(dbus.AddMatch(r))
        try:
            names = (await router.send_and_get_reply(dbus.ListNames())).body[0]
            for n in names:
                if n.startswith(PREFIX):
                    try:
                        self._owners[n] = (await router.send_and_get_reply(dbus.GetNameOwner(n))).body[0]
                    except Exception:
                        pass
            await self._choose_player()
            resync = asyncio.create_task(self._resync_loop())
            try:
                while True:
                    try:
                        msg = await asyncio.wait_for(queue.get(), 15)
                    except asyncio.TimeoutError:
                        # quiet bus: make sure the connection is still alive (raises if not)
                        await asyncio.wait_for(router.send_and_get_reply(dbus.GetId()), 5)
                        continue
                    await self._handle(msg)
            finally:
                resync.cancel()
        finally:
            for h in handles:
                h.close()

    # ---------------- player selection ----------------
    def _candidates(self) -> list[str]:
        out = []
        for p in self.players:
            if p == "*":
                out += sorted(n for n in self._owners if n not in out)
            else:
                # Spotify may register as org.mpris.MediaPlayer2.spotify or ...spotify.instanceNNN
                out += sorted(n for n in self._owners if (n == PREFIX + p or n.startswith(PREFIX + p + ".")) and n not in out)
        return out

    async def _choose_player(self) -> None:
        cands = self._candidates()
        chosen = cands[0] if cands else None
        if len(cands) > 1 and "*" in self.players:
            # prefer a player that is actually playing
            for n in cands:
                st = await self._get(n, "PlaybackStatus")
                if st == "Playing":
                    chosen = n
                    break
        if chosen == self.bus_name and chosen is not None:
            return
        self.bus_name = chosen
        self.owner = self._owners.get(chosen) if chosen else None
        if not chosen:
            self._set_unavailable()
            return
        log.info("following player %s (%s)", chosen, self.owner)
        await self._full_refresh("player")

    def _set_unavailable(self) -> None:
        if self.state.available or self.state.track.title:
            self.state = PlayerState()
            self.on_change("player", self.state)

    # ---------------- D-Bus helpers ----------------
    def _addr(self, name: str | None = None, iface: str = PLAYER_IFACE) -> DBusAddress:
        return DBusAddress(MPRIS_PATH, bus_name=name or self.bus_name, interface=iface)

    async def _get(self, name: str, prop: str):
        try:
            reply = await self.router.send_and_get_reply(Properties(self._addr(name)).get(prop))
            if reply.header.message_type == MessageType.error:
                return None
            return _unwrap(reply.body[0])
        except (DBusErrorResponse, Exception) as e:  # noqa: BLE001 - player may vanish mid-call
            log.debug("Get %s failed: %s", prop, e)
            return None

    async def _get_all(self) -> dict | None:
        try:
            reply = await self.router.send_and_get_reply(Properties(self._addr()).get_all())
            if reply.header.message_type == MessageType.error:
                return None
            return reply.body[0]
        except Exception as e:  # noqa: BLE001
            log.debug("GetAll failed: %s", e)
            return None

    async def call(self, method: str, signature: str | None = None, *args) -> bool:
        if not (self.router and self.bus_name):
            return False
        msg = new_method_call(self._addr(), method, signature, args) if signature else new_method_call(self._addr(), method)
        try:
            reply = await self.router.send_and_get_reply(msg)
            return reply.header.message_type != MessageType.error
        except Exception as e:  # noqa: BLE001
            log.warning("%s failed: %s", method, e)
            return False

    # ---------------- state updates ----------------
    async def _full_refresh(self, reason: str) -> None:
        props = await self._get_all()
        if props is None:
            self._set_unavailable()
            return
        props = {k: _unwrap(v) for k, v in props.items()}
        st = self.state
        st.available = True
        st.player = (self.bus_name or "").removeprefix(PREFIX)
        st.status = props.get("PlaybackStatus", "Stopped") or "Stopped"
        st.track = Track.from_metadata(props.get("Metadata") or {})
        st.can_seek = bool(props.get("CanSeek", True))
        pos = props.get("Position")
        st.pos_ms = (pos or 0) / 1000
        st.anchor = time.monotonic()
        self.on_change(reason, st)
        if reason in ("player", "track"):
            asyncio.get_running_loop().call_later(0.4, lambda: asyncio.ensure_future(self._resync(force=True)))

    async def _handle(self, msg) -> None:
        hdr = msg.header.fields
        member = hdr.get(HeaderFields.member)
        sender = hdr.get(HeaderFields.sender)
        if member == "NameOwnerChanged":
            name, old, new = msg.body
            if not name.startswith(PREFIX):
                return
            if new:
                self._owners[name] = new
            else:
                self._owners.pop(name, None)
            if name == self.bus_name and not new:
                self.bus_name = self.owner = None
            await self._choose_player()
            return
        if sender != self.owner:
            if member == "PropertiesChanged" and "*" in self.players:
                await self._choose_player()
            return
        st = self.state
        if member == "Seeked":
            st.pos_ms = msg.body[0] / 1000
            st.anchor = time.monotonic()
            self.on_change("position", st)
            return
        if member == "PropertiesChanged":
            iface, changed, _inv = msg.body
            if iface != PLAYER_IFACE:
                return
            changed = {k: _unwrap(v) for k, v in changed.items()}
            if "Metadata" in changed:
                new_track = Track.from_metadata(changed["Metadata"])
                if new_track.id != st.track.id or new_track.title != st.track.title:
                    if "PlaybackStatus" in changed:
                        st.status = changed["PlaybackStatus"]
                    st.track = new_track
                    await self._full_refresh("track")
                    return
                st.track = new_track  # e.g. art URL arrived late
                self.on_change("meta", st)
            if "PlaybackStatus" in changed:
                st.pos_ms = st.position()  # freeze/unfreeze at the extrapolated point...
                st.status = changed["PlaybackStatus"]
                st.anchor = time.monotonic()
                self.on_change("status", st)
                await self._resync(force=True)  # ...then correct with the real value

    async def _resync(self, force: bool = False) -> None:
        if not (self.router and self.bus_name):
            return
        pos = await self._get(self.bus_name, "Position")
        if pos is None:
            return
        st = self.state
        actual = pos / 1000
        predicted = st.position()
        # Some Spotify builds intermittently report 0 while playing; don't snap back to 0 then.
        if actual == 0 and st.playing and predicted > 2500:
            self._zero_pos_since = self._zero_pos_since or time.monotonic()
            if time.monotonic() - self._zero_pos_since < 10:
                return
        else:
            self._zero_pos_since = None
        diff = actual - predicted
        if force or abs(diff) > 60:
            st.pos_ms = actual
            st.anchor = time.monotonic()
            self.on_change("position", st)

    async def _resync_loop(self) -> None:
        while True:
            await asyncio.sleep(self.resync_interval if self.state.playing else 5.0)
            try:
                await self._resync()
            except Exception as e:  # noqa: BLE001
                log.debug("resync failed: %s", e)

    # ---------------- controls ----------------
    async def raise_window(self):
        if not (self.router and self.bus_name):
            return False
        msg = new_method_call(self._addr(iface="org.mpris.MediaPlayer2"), "Raise")
        try:
            await self.router.send_and_get_reply(msg)
            return True
        except Exception:  # noqa: BLE001
            return False

    async def play_pause(self):
        return await self.call("PlayPause")

    async def next(self):
        return await self.call("Next")

    async def previous(self):
        return await self.call("Previous")

    async def seek_relative(self, delta_ms: int):
        ok = await self.call("Seek", "x", int(delta_ms * 1000))
        await asyncio.sleep(0.15)
        await self._resync(force=True)
        return ok

    async def set_position(self, pos_ms: int):
        tid = self.state.track.id
        if tid.startswith("/"):
            ok = await self.call("SetPosition", "ox", tid, int(pos_ms * 1000))
        else:
            ok = await self.seek_relative(int(pos_ms - self.state.position()))
        await asyncio.sleep(0.15)
        await self._resync(force=True)
        return ok
