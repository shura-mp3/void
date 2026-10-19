# Testing — what was verified, and what wasn't

VOID was built in an **Ubuntu 24.04 cloud container (Python 3.13)**, not on the Nobara machine.
The container had no KDE Plasma, no display, no Spotify and no audio device. Crimson Desktop was
inspected from its GitHub copy (`shura-mp3/crimson-desktop`, commit `a504041`); your local copy
may differ.

```bash
cd tests && python3 -m unittest discover -v
```

Last full run: **77 tests, 0 failures, 0 skipped** (with tmux, btop, node, dbus-run-session,
zsh, Chromium headless shell and `NODE_PATH` pointing at react/react-dom/playwright-core).
Without those optional tools the matching tests skip themselves.

## Real programs exercised

| | how |
|---|---|
| void-core | real process on a private D-Bus session with a fake Spotify MPRIS player: follows the player, fetches synced word-level lyrics from a mock LRCLIB, handles a track change and pause, answers status |
| Spotify bridge | real TCP WebSocket handshake: Spotify's origin → 101, other origin → 403; VOID uses port 47812, not Crimson's 47811 |
| VOID Spotify page + theme.js | **headless Chromium**, page served as `https://xpui.app.spotify.com` with a mocked Spicetify API, connected to the real void-core: "CORE LINKED", word sync at 4.7 s ("You could" bright, "be everything" `#777777`), +100 ms offset round-trips through the core, profile class applied, no JS errors |
| tmux dashboard | real tmux 3.4: five panes, idempotent build, btop pane ≥ 80×24, panes alive |
| btop 1.3, fastfetch 2.70 | rendered with VOID's generated configs; every colour on screen checked to be grey |
| launch / stop | Konsole double: one window only (second `void launch` refused), exactly one void-core process, `void stop` leaves no tmux server and no void-core |
| void-shell | real bash and zsh 5.9: user rc loads first, user aliases kept, VOID layer added, `VOID_PLAIN=1` gives a plain shell |
| wallpaper | Pillow on synthetic images: ranking by content (a file named "black_and_grey_monochrome" that is bright red ranks last), derivative exactly 1920×1080 and fully grey, original byte-identical |

## Switching lifecycle (sandboxed homes, test doubles)

Doubles: `kreadconfig6`/`kwriteconfig6` (KDE INI), `plasma-apply-*` (write what the real tools
change), `qdbus6` (Plasma scripting runs **VOID's real JavaScript in node** against a fake
desktop API), `kscreen-doctor` (two monitors, HDMI-A-1 on the right), `systemctl --user`, `konsole`,
`spicetify` (models config lists, backup, apply, restore, stock/applied state; from Crimson's tests).

| scenario | result |
|---|---|
| Crimson desktop → activate | VOID scheme, crimson accent removed, decoration, KWin rule at 2560,0 1920×1080, Konsole default VOID, wallpaper on the **right** desktop only, Crimson services stopped + disabled, Spicetify VOID theme, Crimson app set aside, Spotify patched with VOID css |
| activate twice | identical state, no duplicate journal entries or KWin rules |
| activate → deactivate | **every compared setting identical to before** (all KDE INI files, both wallpapers, services, Spicetify config, applied css) |
| two full round trips | identical; original record still Crimson |
| user changes Konsole default while active | kept on deactivate, everything else reverted |
| failure mid-activation (Plasma style step) | exit 1, state `failed`; `void deactivate` → identical to before; or `void activate` again completes |
| `spicetify apply` fails | Spicetify settings rolled back, rest of VOID active, deactivate clean |
| `void restore --uninstall` | pre-VOID state, VOID files removed, Crimson's Spotify files untouched |
| stock desktop + stock Spotify, patch **approved on a pseudo-terminal** | `spicetify backup apply`; deactivate → `spicetify restore` → `.spa` files byte-identical |
| same with `--yes` only | patching is **not** approved (privileged prompts never auto-answered) |
| declining the first question | nothing changed |
| no KDE tools | refuses cleanly, nothing recorded |
| first-activation archive | contains the original `kdeglobals` (CrimsonNight), `konsolerc`, Spicetify config |

## Performance

Measured in the container with music playing (fake Spotify), the full dashboard attached at
210×56, a 30 s window, CPU as % of one core. Not included: Konsole's own rendering (no display
there) and CAVA (no audio device, so no spectrum process).

| | minimal | balanced | showcase |
|---|---|---|---|
| music pane | 0.23 % | 0.80 % | 1.57 % |
| data rain | 0.00 % (static) | 0.43 % | 0.83 % |
| btop | 0.07 % | 0.10 % | 0.20 % |
| clock | 0.00 % | 0.07 % | 0.03 % |
| fetch | 0.00 % | 0.00 % | 0.00 % |
| void-core | 0.10 % | 0.10 % | 0.10 % |
| tmux server | 0.27 % | 1.23 % | 2.00 % |
| **total** | **0.67 %** | **2.73 %** | **4.73 %** |

Memory: about 20–35 MiB per pane process and 27 MiB for void-core, about 175 MiB in total.

## Not tested (needs your machine)

* Real KDE Plasma 6 / KWin: that `plasma-apply-colorscheme`, the KWin rule (placement, borderless,
  below), Plasma scripting wallpaper and the lock-screen keys behave as their doubles do.
* Konsole itself: profile loading, `--hide-tabbar` / `--hide-menubar`, tab-title matching for the
  rule, font rendering of the block font.
* Real Spotify + real Spicetify: `user.css` selectors against your Spotify version, Full App
  Display, Spicetify's custom `void-muted` colour key, the `sudo chmod` path, Flatpak sandbox access
  to the loopback port.
* Real CAVA with PipeWire, GameMode detection, `dnf repoquery` on Nobara.
* The actual wallpaper pack (`~/Downloads/home/jan/Downloads/pack 1/` didn't exist in the
  container). The picker ran on synthetic images only, so the choice for your pack hasn't been made yet.

`void inspect` (read-only) and `void health` are the first things to run on the real system.
