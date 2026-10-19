# Switching, backups and restore

## Three levels of undo

| command | returns to | typical use |
|---|---|---|
| `void deactivate` | the desktop **just before the current activation**, e.g. Crimson | everyday switching back |
| `void restore` | the desktop **before VOID was ever activated** | giving VOID up |
| `void restore --files` | whole config files from the archive taken at the first activation | last resort, if KDE config got damaged by something else |

`void restore --uninstall` also removes every file VOID installed: Konsole profiles, colour
scheme, user unit, autostart entry, and the Spicetify theme/app folders marked `.void-desktop`.
It only removes files that are still byte-identical to what VOID wrote. The project folder,
`~/.config/void-desktop/config.toml`, caches and backups are kept.

## The journal

Everything VOID changes outside its own files goes through
`~/.local/state/void-desktop/switch/`:

* `session.json`: for each setting changed by the current activation, the value before it
  (`previous`) and what VOID set (`applied`). The entry is written **before** the change is
  made, so after a crash or a failed step the journal still knows exactly what to undo.
* `original.json`: the value from before VOID touched each setting **for the first time ever**.
  Later activations never overwrite it.
* `state.json`: `inactive | activating | active | deactivating | failed`, plus the last error.
* `history/`: finished session/original records, kept for reference.

A setting is a `(kind, key)` pair. Each kind has a handler that reads and writes it through a
supported interface:

| kind | read / write through |
|---|---|
| `kconfig` | `kreadconfig6` / `kwriteconfig6` (decoration, KWin rule, lock screen, Konsole default profile, fonts) |
| `colorscheme` | scheme name + accent → `plasma-apply-colorscheme [--accent-color]` (repaints running apps) |
| `desktoptheme` | `plasma-apply-desktoptheme` |
| `cursortheme` | `plasma-apply-cursortheme` |
| `wallpaper` | Plasma desktop scripting (`evaluateScript`) on the desktop whose screen sits at the monitor's position — one entry per monitor, so both screens come back |
| `kitty` | VOID's three marked lines at the end of `kitty.conf` (present / absent / no file) |
| `service` | `systemctl --user start/stop/enable/disable` (Crimson's units, void-core) |
| `spicetify` | `spicetify config …` (lists like `extensions` are diffed item by item) |

### Rules

* **Idempotent.** Activating twice records nothing twice: the second run finds every value
  already set and changes nothing. Deactivating when inactive is a no-op.
* **Your changes win.** If a value is no longer what VOID set (you changed the Konsole default
  profile while VOID was active, say), deactivate keeps yours and says so. `--force` reverts it anyway.
* **Partial failure.** A failed activation leaves `state = failed` and a journal of everything
  applied up to that point. `void deactivate` undoes exactly that; `void activate` continues.
  Reverting also continues past a failing setting and reports it, and the session record is
  kept so you can retry.
* **One manager at a time.** Activation pauses (stops and disables) `crimson-core` and
  `crimson-dashboard` if they were running or enabled, and records how they were.
  Deactivation restores them last, after VOID's own settings are gone.

### Spotify ordering

Spicetify has one active theme. Activation journals the previous theme, colour scheme,
extensions and custom apps, then sets VOID and runs `spicetify apply`. Deactivation depends on
what Spotify was like before:

* **another theme (e.g. Crimson)**: settings are put back first, then `spicetify apply`.
* **stock Spotify**: `spicetify restore` runs **first**, while the config still knows where
  Spotify is, then the settings are put back. A test showed that the other order leaves Spotify
  patched; the restored `.spa` files are checked byte for byte.

If `spicetify apply` fails during activation (usually a Spotify version that your Spicetify
doesn't support yet), only the Spicetify settings are rolled back and the rest of VOID stays active.

## Backups

* Before **every** activation: `~/.local/state/void-desktop/backups/<time>-activate.tar.gz`
  with a `.json` manifest listing which files existed and which didn't: `kdeglobals`, `kwinrc`,
  `kwinrulesrc`, `breezerc`, `plasmarc`, `kcminputrc`, `kscreenlockerrc`, `konsolerc`, `kitty/kitty.conf`, `kglobalshortcutsrc`, the Plasma
  desktop layout (`plasma-org.kde.plasma.desktop-appletsrc`, which holds the wallpaper
  assignments), Spicetify's `config-xpui.ini`, and `~/.config/autostart`. The last 10 are kept.
  The first one is recorded as the *original* archive.
* `void restore --list` lists them. To pull a single file out by hand:
  `tar -xzf <archive> -C ~ .config/konsolerc`.

## What is never touched

Crimson Desktop's source, assets and git history (VOID only reads its lyric cache and
`.lrc` folder) · your `~/.bashrc` / `~/.zshrc` / fish config · `~/.tmux.conf` ·
`~/.config/btop` · `~/.config/fastfetch/config.jsonc` · display resolution, refresh rate, scaling
and arrangement · SDDM / login screen · system files (the only privileged actions are the
optional `sudo dnf install` and Spicetify's documented `sudo chmod`, each asked separately and
never answered by `--yes`).
