# Architecture and decisions

## Starting point: Crimson Desktop

Crimson Desktop (`~/Projects/crimson-desktop`, inspected read-only at commit `a504041`) has:

* **crimson-core**: an asyncio backend owning MPRIS (jeepney, signal-driven, position modelled as
  an anchor and corrected every 1.5 s), lyrics (local `.lrc` → cache → LRCLIB `/api/get` →
  `/api/search` with duration matching, negative cache, automatic retries), album art, CAVA,
  `/proc` stats and GameMode detection. It serves newline JSON over a unix socket and a loopback
  WebSocket for Spotify.
* a Qt/QML layer-shell dashboard, a Textual "Terminal OS" for Konsole, a Spicetify theme + app,
  and stub-based tests.

## What VOID reuses, and how

VOID copies the backend modules (`core`, `mpris`, `lyrics`, `lrc`, `audio`, `sysinfo`,
`bridge`, `client`) into `src/void/` and maintains them independently. There are no imports from
Crimson's tree and no dependency on its private internals. The differences:

| | Crimson | VOID |
|---|---|---|
| socket | `$XDG_RUNTIME_DIR/crimson-desktop/core.sock` | `$XDG_RUNTIME_DIR/void-desktop/core.sock` |
| Spotify bridge | `127.0.0.1:47811` | `127.0.0.1:47812` |
| profiles | low / balanced / high + layout | **minimal / balanced / showcase** |
| lyric cache | its own | its own, plus a **read-only** lookup in Crimson's cache and `.lrc` folder |

**One backend at a time.** Activation stops crimson-core, so Spotify is only ever watched by
one process. Lyrics Crimson already fetched are reused: same cache-key scheme, read-only,
positive results only, copied into VOID's cache. Nothing is fetched twice.

## The dashboard: Konsole + tmux, not a second QML dashboard

The brief allows either. I chose **Konsole + tmux** for the main dashboard:

* Four of the five panes *are* terminal programs (fastfetch, btop, clock, rain). In a terminal
  they render natively, with Konsole's font engine at the monitor's real resolution, so
  there's no blur at any scale.
* A second QML dashboard would compete with Crimson's QML dashboard for the same monitor and
  duplicate its architecture: the brief warns against competing dashboard systems.
* The music pane is a terminal program too. The active lyric is drawn in a 5×5 block font
  (`bigfont.py`, three rows tall), made of glyphs Konsole renders itself, so it stays sharp.
  Lines that the block font can't spell (non-Latin scripts) fall back to bold normal text.

On Wayland a client can't place its own window, so VOID adds a **KWin rule**. It matches window
class `konsole|alacritty|void-dashboard` *and* title `VOID//DASHBOARD` (the dashboard profile's
fixed tab title) and sends the window to the right-hand monitor's geometry (KScreen logical
coordinates): maximized, borderless, below normal windows, out of the task bar and Alt+Tab.

`void launch` refuses to open a second dashboard window (pid file + `/proc` check). The tmux
session is built once (`void dashboard build` is idempotent). Each pane runs under a small
supervisor that restarts it if it exits (with backoff). A tmux hook re-fits pane sizes on every
attach or resize, so btop keeps its 80×24 minimum and the music pane keeps at least 14 rows.

## KDE look

* **Colour scheme `VOID Monochrome`**, generated from the tokens. The accent comes from the
  scheme, not the wallpaper, because a Crimson accent would otherwise tint selections red.
* **Plasma style: Breeze ("default")**, which follows the colour scheme. I didn't ship a custom
  Plasma style package: a colours-only package depends on Plasma's fallback-theme behaviour,
  which couldn't be verified here, and if that guess were wrong the panels would draw
  incorrectly. Breeze-following-the-scheme is the supported path and makes the panel, task
  manager, launcher, system tray and notifications monochrome.
* **Window decoration: Breeze** with tiny borders, neutral black shadows and no title-bar
  separator; animation speed 0.7 (restrained, not off).
* **Cursor**: only a monochrome theme that's already installed (Bibata-Modern-Classic or Breeze).
* **Fixed-width font**: JetBrains Mono if installed.
* **Global theme / SDDM**: not changed. A look-and-feel package can reset panel layouts, and
  SDDM needs root.

## Konsole

Two profiles, never overwriting existing ones:

* **VOID**: everyday shell. `Command=bin/void-shell` starts your login shell with VOID's layer
  added *after* your own rc: bash via `--rcfile`, zsh via a `ZDOTDIR` shim that sources your real
  `.zshrc`, fish via `-C`. No dotfile is edited. It adds a monochrome prompt (left alone if you
  use starship or oh-my-posh), `void`/`vfetch`/`vmusic`/`vdash`, and one Geass fastfetch per
  window. Escape hatches: `VOID_PLAIN=1`, or `touch ~/.config/void-desktop/shell.disabled`.
  `void-shell` is POSIX sh and falls back to your plain shell whenever anything is missing.
* **VOID Dashboard**: used only by `void launch`.

## Design tokens

`config/tokens.toml` holds the 8 palette colours, 16 ANSI greys, terminal font/size/opacity and
the Spotify key map. `src/void/tokens.py` generates every palette file. The terminal programs read
the tokens at runtime. Tests check that the generated files are current and that no file in the
repo uses a colour that isn't a pure grey (r = g = b).

ANSI colours are grey steps that differ by lightness, so `ls`, git diffs and compiler messages
stay distinguishable. All 16 are ≥ 3:1 against the background, and body text is 15.9:1. The
brief's `#777777` is 4.47:1, just below AA for small text, so VOID uses it only for labels and
inactive lyrics.

## Performance

* void-core: event-driven; one position check every 1.5 s while playing; stats every 2–6 s.
* CAVA runs only while something shows the spectrum *and* music plays; it stops 2.5 s after pause.
  Minimal turns it off.
* Panes diff their frames line by line, so an unchanged screen writes nothing. The clock wakes
  once a second (once a minute in minimal), the music pane redraws at the profile's fps only
  while playing (1 fps otherwise), and the rain is a static frame in minimal.
* GameMode (or load above `cores × 0.9`) drops everything to minimal automatically.
* void-core's unit has `Nice=5`, `CPUWeight=40`, `MemoryMax=300M`.
