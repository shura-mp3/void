# VOID Spotify

## What you get

| | what it is | source |
|---|---|---|
| **VOID theme** | Spotify's colours from VOID's tokens (`color.ini`), hairline frames, monochrome rows, cards, menus, search, sliders; Spotify's green accent tokens remapped to white; album/artist header gradients removed; native lyrics view in VOID greys; mono font for small technical labels only | `spicetify/Themes/VOID` |
| **VOID page** (sidebar) | now playing, synced lyrics (line, karaoke or single-word), per-track offsets, CAVA spectrum, all from void-core | `spicetify/CustomApps/void` |
| **Full App Display** | full-window now playing, styled monochrome (its background art is grayscaled) | bundled with every Spicetify release (`fullAppDisplay.js`, LGPL-2.1) |
| **Live profile** | minimal / GameMode removes transitions without restarting Spotify | `theme.js` ↔ void-core |
| **Grayscale artwork** (off by default) | `[spicetify] grayscale_art = true`, or per-Spotify in devtools: `Spicetify.LocalStorage.set("void:grayscale-art","1")` | CSS filter only; files untouched |

Album artwork keeps its colour by default: it's content, not chrome.

## Commands

```bash
void spotify inspect           # read-only: package format, version, patch state, Spicetify config
void spotify status            # theme/extensions/apps now, applied?, bridge connected?
void spotify apply             # the Spotify part of `void activate` on its own (VOID must be active)
void spotify revert            # the Spotify part of `void deactivate` on its own
void spotify install-spicetify # official release tarball → ~/.spicetify (asks first; no install script)
```

## Safety and compatibility

* **Package format is detected, never assumed**: Flatpak (system/user), RPM, snap (read-only,
  unsupported) and Spicetify's own search paths. With several installs VOID won't guess: set
  `[spicetify] target`.
* **Patch state** uses Spicetify's own classification (`stock / applied / mixed / invalid`).
  `mixed`/`invalid` are refused with the fix to apply.
* **Compatibility is established by Spicetify itself**: if `spicetify apply` fails (usually a
  Spotify version Spicetify doesn't support yet), VOID rolls the Spicetify settings back
  immediately and leaves Spotify working. Newer Spicetify is never installed automatically.
* **Asked separately, never by `--yes`**: the first patch of a stock Spotify, Spicetify's documented
  `sudo chmod` for system-wide installs, and downloading Spicetify.
* **Restarting Spotify** (apply/restore) is asked first if Spotify is running.
* Only `app.last-launched-version` is read from Spotify's prefs; no credentials, tokens or caches.

## Coexisting with Crimson Spotify

Spicetify has one active theme. VOID records Crimson's theme, colour scheme, extensions and
custom apps, switches to VOID, and **sets Crimson's custom app aside** while VOID is active,
because it needs crimson-core, which is paused. Crimson's theme and app folders stay in place.
`void deactivate` puts Crimson's configuration back and re-applies it.

## The bridge

`theme.js` opens one WebSocket to `ws://127.0.0.1:47812`. The bridge accepts only Spotify's UI
origin (`https://xpui.app.spotify.com`), so ordinary web pages get 403. It allows only
`sub` / `offset` / `ping` (offset clamped to ±2000 ms) and never exposes system stats. Without
void-core Spotify works normally; the page shows *VOID-CORE OFFLINE* and the theme retries with
backoff (2 s → 60 s).

## Extensions evaluated and not added

| | why not |
|---|---|
| lyrics-plus (bundled custom app) | its default providers use a shared Musixmatch token and Spotify's internal lyrics endpoint, and it would duplicate void-core's lookups |
| popupLyrics.js (bundled) | providers include Spotify's internal endpoint, Musixmatch with a user token and a third-party Netease proxy |
| Spicetify Marketplace | its documented installer pipes a remote script into `sh`; it would allow unreviewed extensions |
| community visualizers | not verified; in-client code has no access to audio. VOID's spectrum is real CAVA output from void-core |

## Limits

* **Spotify updates remove the theme** (Spicetify's nature). `void health` notices; run
  `void spotify apply` again.
* `user.css` targets Spotify class names that maintained themes rely on. A Spotify redesign can
  stop some rules matching; the worst case is a plainer look, never a broken client. Colours come
  from `color.ini` variables, which are robust.
* The native lyrics view is themed through Spotify's `--lyrics-color-*` variables. That's
  best-effort: those internals aren't a public API.
