"""Lyrics lookup: local .lrc files -> on-disk cache -> LRCLIB (https://lrclib.net).

LRCLIB is a free, open, community lyrics database with a public API that needs no key.
Nothing here touches Spotify's own lyrics endpoints.

Every lookup returns a dict:
    status   "synced" | "plain" | "instrumental" | "none" | "error"
    source   human-readable origin ("lrclib", "local:<file>", ...)
    lines    [{"t": ms, "text": str, "w": [[ms, word(, end_ms)], ...] | None}]
    plain    unsynced text (status == "plain")
    has_words, lrc_offset
"""

from __future__ import annotations

import difflib
import hashlib
import json
import logging
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import __version__, lrc, paths

log = logging.getLogger(__name__)

USER_AGENT = f"void-desktop/{__version__} (personal desktop lyrics display)"

_FEAT = re.compile(r"\s*[\(\[](feat\.?|ft\.?|with)\s[^\)\]]*[\)\]]", re.I)
_SUFFIX = re.compile(
    r"\s+[-–—]\s+(.*\b(remaster(ed)?|live|mono|stereo|version|edit|mix|demo|acoustic|bonus|from)\b.*)$", re.I
)
_PAREN_SUFFIX = re.compile(r"\s*[\(\[][^\)\]]*\b(remaster(ed)?|live|mono|stereo|version|edit|demo|bonus)\b[^\)\]]*[\)\]]", re.I)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def clean_title(title: str) -> str:
    t = _FEAT.sub("", title or "")
    t = _SUFFIX.sub("", t)
    t = _PAREN_SUFFIX.sub("", t)
    return t.strip() or (title or "")


def primary_artist(artist: str) -> str:
    return re.split(r",|;| & | feat\.? | ft\.? | x ", artist or "", maxsplit=1, flags=re.I)[0].strip()


def similarity(a: str, b: str) -> float:
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _result(status: str, source: str = "", lines=None, plain=None, offset=0, has_words=False) -> dict:
    return {
        "status": status,
        "source": source,
        "lines": lines or [],
        "plain": plain,
        "lrc_offset": offset,
        "has_words": has_words,
    }


def from_lrc_text(text: str, source: str) -> dict:
    parsed = lrc.parse(text)
    if parsed["lines"]:
        return _result("synced", source, parsed["lines"], offset=parsed["offset"], has_words=parsed["has_words"])
    plain = "\n".join(l for l in text.splitlines() if not lrc.TAG.match(l.strip())).strip()
    return _result("plain", source, plain=plain) if plain else _result("none", source)


class LyricsService:
    def __init__(self, cfg: dict):
        self.cfg = cfg["lyrics"]
        self._local_index: dict[str, Path] | None = None
        self._local_index_time = 0.0

    # ---------- public ----------
    def lookup(self, artist: str, title: str, album: str, duration_ms: int, force_refresh: bool = False) -> dict:
        if not title:
            return _result("none")
        local = self._find_local(artist, title)
        if local:
            try:
                return from_lrc_text(local.read_text(errors="replace"), f"local:{local.name}")
            except OSError as e:
                log.warning("cannot read %s: %s", local, e)

        key = self._cache_key(artist, title, duration_ms)
        if not force_refresh:
            cached = self._cache_get(key)
            if cached is not None:
                cached["source"] = (cached.get("source") or "") + " (cached)"
                return cached

        if not self.cfg.get("lrclib", True):
            return _result("none", "lrclib disabled")
        try:
            res = self._lrclib(artist, title, album, duration_ms)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            log.warning("LRCLIB lookup failed: %s", e)
            return _result("error", f"network: {e}")  # not cached, retried next time
        self._cache_put(key, res)
        return res

    # ---------- local files ----------
    def _dirs(self) -> list[Path]:
        dirs = [paths.USER_LYRICS_DIR] + [Path(d).expanduser() for d in self.cfg.get("local_dirs", [])]
        if self.cfg.get("use_crimson_cache", True):
            dirs.append(paths.CRIMSON_USER_LYRICS)  # your .lrc files for Crimson work in VOID too (read-only)
        return [d for d in dirs if d.is_dir()]

    def _find_local(self, artist: str, title: str) -> Path | None:
        if time.monotonic() - self._local_index_time > 30 or self._local_index is None:
            idx: dict[str, Path] = {}
            for d in self._dirs():
                for p in d.rglob("*.lrc"):
                    idx.setdefault(norm(p.stem), p)
            self._local_index, self._local_index_time = idx, time.monotonic()
        idx = self._local_index
        for cand in (f"{artist} - {title}", f"{primary_artist(artist)} - {title}",
                     f"{primary_artist(artist)} - {clean_title(title)}", title, clean_title(title)):
            p = idx.get(norm(cand))
            if p:
                return p
        return None

    # ---------- cache ----------
    def _cache_key(self, artist: str, title: str, duration_ms: int) -> str:
        raw = f"{norm(primary_artist(artist))}|{norm(clean_title(title))}|{round((duration_ms or 0) / 2000)}"
        return hashlib.sha1(raw.encode()).hexdigest()

    def _cache_get(self, key: str) -> dict | None:
        hit = self._cache_read(paths.LYRICS_CACHE / f"{key}.json")
        if hit is None and self.cfg.get("use_crimson_cache", True):
            # Crimson Desktop uses the same key scheme; a positive result it already fetched is reused
            # (copied into VOID's cache, Crimson's file is only read) so the track isn't fetched twice.
            crimson = self._cache_read(paths.CRIMSON_LYRICS_CACHE / f"{key}.json", positive_only=True)
            if crimson is not None:
                self._cache_put(key, crimson)
                hit = dict(crimson, source=(crimson.get("source") or "") + " via crimson")
        return hit

    def _cache_read(self, f: Path, positive_only: bool = False) -> dict | None:
        try:
            data = json.loads(f.read_text())
        except (OSError, ValueError):
            return None
        res = data.get("result")
        if res and res.get("status") in ("synced", "plain", "instrumental"):
            return res
        if positive_only:
            return None
        # negative entry: honour only for negative_cache_hours
        if time.time() - data.get("fetched", 0) < self.cfg.get("negative_cache_hours", 24) * 3600:
            return res or _result("none", "lrclib")
        return None

    def _cache_put(self, key: str, res: dict) -> None:
        paths.LYRICS_CACHE.mkdir(parents=True, exist_ok=True)
        f = paths.LYRICS_CACHE / f"{key}.json"
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps({"fetched": time.time(), "result": res}))
        tmp.replace(f)

    def forget(self, artist: str, title: str, duration_ms: int) -> None:
        (paths.LYRICS_CACHE / f"{self._cache_key(artist, title, duration_ms)}.json").unlink(missing_ok=True)

    # ---------- LRCLIB ----------
    def _http_json(self, endpoint: str, params: dict):
        url = self.cfg.get("lrclib_url", "https://lrclib.net").rstrip("/") + endpoint + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise

    def _record_to_result(self, rec: dict) -> dict:
        if rec.get("instrumental"):
            return _result("instrumental", "lrclib")
        if rec.get("syncedLyrics"):
            res = from_lrc_text(rec["syncedLyrics"], "lrclib")
            if res["status"] == "synced":
                return res
        if rec.get("plainLyrics"):
            return _result("plain", "lrclib", plain=rec["plainLyrics"])
        return _result("none", "lrclib")

    def _score(self, rec: dict, artist: str, title: str, duration_s: float) -> float:
        tol = self.cfg.get("duration_tolerance", 3)
        if duration_s and rec.get("duration"):
            diff = abs(float(rec["duration"]) - duration_s)
            if diff > tol:
                return -1.0
            dur_score = 1 - diff / (tol + 1)
        else:
            dur_score = 0.5
        t = max(similarity(rec.get("trackName", ""), title), similarity(rec.get("trackName", ""), clean_title(title)))
        a = max(similarity(rec.get("artistName", ""), artist), similarity(rec.get("artistName", ""), primary_artist(artist)))
        if t < 0.6 or a < 0.5:
            return -1.0
        synced = 0.35 if rec.get("syncedLyrics") else (0.1 if rec.get("plainLyrics") else 0)
        return t * 1.2 + a + dur_score * 0.8 + synced

    def _lrclib(self, artist: str, title: str, album: str, duration_ms: int) -> dict:
        duration_s = (duration_ms or 0) / 1000
        best: dict | None = None
        # 1) exact signature match (LRCLIB validates duration within +-2 s itself)
        if artist and duration_s:
            for t in dict.fromkeys([title, clean_title(title)]):
                rec = self._http_json("/api/get", {
                    "track_name": t, "artist_name": artist, "album_name": album or "", "duration": round(duration_s)})
                if rec:
                    res = self._record_to_result(rec)
                    if res["status"] in ("synced", "instrumental"):
                        return res
                    best = best or rec
        # 2) search and rank, preferring synced + correct duration
        candidates = []
        for t in dict.fromkeys([title, clean_title(title)]):
            recs = self._http_json("/api/search", {"track_name": t, "artist_name": primary_artist(artist)}) or []
            candidates.extend(recs)
            if any(r.get("syncedLyrics") for r in recs):
                break
        scored = sorted(((self._score(r, artist, title, duration_s), r) for r in candidates),
                        key=lambda x: x[0], reverse=True)
        if scored and scored[0][0] > 0:
            res = self._record_to_result(scored[0][1])
            if res["status"] != "none":
                return res
        if best:
            return self._record_to_result(best)
        return _result("none", "lrclib")
