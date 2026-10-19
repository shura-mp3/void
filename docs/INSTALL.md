# Installing VOID — step by step

For Nobara Linux (KDE Plasma 6, Wayland). Everything except the optional `sudo dnf install` and
Spicetify's optional `sudo chmod` is user-level, and every change can be undone (step 10).

Expected time: about 10 minutes. Keep a terminal open the whole time; steps 5–7 ask questions.

---

## 1. Check the basics (read-only)

```bash
echo $XDG_SESSION_TYPE                 # should print: wayland
plasmashell --version                  # Plasma 6.x
python3 --version                      # 3.11 or newer (Nobara 42: 3.13)
git --version
```

If Crimson Desktop is running, leave it as it is: VOID pauses Crimson's services itself and
brings them back when you switch back.

## 2. Get the code

```bash
mkdir -p ~/Projects
git clone https://github.com/shura-mp3/void.git ~/Projects/void
cd ~/Projects/void
```

*(If you got `void.tar.gz` instead: `tar -xzf void.tar.gz -C ~/Projects && cd ~/Projects/void`.)*

Crimson stays where it is (`~/Projects/crimson-desktop`) — VOID never modifies it.

## 3. Install dependencies and the user-level pieces

```bash
bin/void install
```

What happens:

1. It lists missing tools. Required: `tmux`, `python3-jeepney`. Optional (VOID has built-in
   fallbacks): `fastfetch`, `btop`, `cava`, `python3-pillow`, `playerctl`, `tty-clock`, `cmatrix`.
2. It checks which ones exist in your enabled Nobara/Fedora repositories and prints **one**
   command, e.g. `sudo dnf install tmux btop cava python3-pillow`. Answer **y** to run it (you'll
   be asked for your password), or **n** and run it yourself later. No COPR or third-party repos
   are added.
3. It creates `~/.config/void-desktop/config.toml` (all options documented), the `void` command
   in `~/.local/bin`, the `void-core` systemd **user** unit (not enabled at boot), the Konsole
   profiles and the fastfetch config. **Nothing visible changes yet.**

From here on you can type `void` instead of `bin/void` (if `~/.local/bin` is on your PATH —
it is by default on Nobara; otherwise open a new terminal).

## 4. Inspect your system (read-only)

```bash
void inspect
```

Check the report (also saved to `docs/INSPECTION.md`):

* **monitors** — `RIGHT/DASH →` must be your **right-hand** monitor and `LEFT →` the other one. If not,
  set it in `~/.config/void-desktop/config.toml`:
  ```toml
  [dashboard]
  monitor = "HDMI-A-1"     # the connector name shown by void inspect
  ```
* **wallpaper pack** — should say `… N image(s)` for `~/Downloads/home/jan/Downloads/pack 1`.
* **Spotify / Spicetify** — package type, version, and whether Spicetify is installed.
* **Crimson Desktop** — which services are running (they'll be paused on activation).

Optional: preview both screens' wallpapers before activating:

```bash
void wallpaper                         # ranks the pack, renders both screens, sets nothing
xdg-open ~/Projects/void/assets/wallpapers/generated/preview.png      # both monitors, real layout
xdg-open ~/Projects/void/assets/wallpapers/generated/candidates.jpg   # the ranking
# choose yourself if you like (same image everywhere, or one per side):
void wallpaper --pick  "$HOME/Downloads/home/jan/Downloads/pack 1/a.png"
void wallpaper --left  "$HOME/Downloads/home/jan/Downloads/pack 1/a.png" --right ".../b.png"
```
(to keep a manual choice for `void activate`, put it in config.toml: `[wallpaper] pick_left` / `pick_right`)

## 5. Activate VOID

```bash
void activate
```

You'll be asked, in order:

| question | answer |
|---|---|
| `activate VOID now?` | **y** |
| `use these wallpapers?` (shows the plan for both monitors) | **y**, or **n** for the procedural VOID wallpapers |
| (Spotify, only if it's never been patched) `let Spicetify patch Spotify now?` | **y** to theme Spotify — `void deactivate` returns it to stock |
| (Spotify, system Flatpak/RPM only) `run these two sudo commands now?` | read the two `chmod` commands; **y** to allow theming, **n** to skip Spotify |
| (if Spotify is running) `Spicetify restarts Spotify … Apply now?` | **y** (playback pauses briefly) |

At the end the dashboard opens on the right monitor. If anything fails, the message says so and
`void deactivate` undoes whatever had been applied.

**If Spicetify isn't installed**, activation skips Spotify and tells you. To add it:

```bash
void spotify install-spicetify         # official release, shows the checksum, asks first
void spotify apply
```

## 6. Make Konsole pick up the VOID profile

**Close every Konsole window once**, then open a new one (Ctrl+Alt+T). You should see the Geass
fastfetch and the monochrome prompt. Your aliases and `.bashrc` still work.

Plain shell when you want one: `VOID_PLAIN=1 konsole`.

### Kitty

If Kitty is installed, activation also makes every Kitty window VOID (three marked lines at the end of
`kitty.conf`; your settings and Crimson's include stay). Without touching anything:

```bash
void kitty            # or scripts/launch-kitty.sh — VOID-mode Kitty
void kitty lyrics     # full-page synced lyrics (Meta+Alt+L after your next login)
```

## 7. Check it worked

```bash
void status
void health                            # "healthy (VOID active)" is what you want
```

Then look for:

- [ ] Right monitor: dashboard with five panes; Geass + system info, btop, data rain, clock, music.
- [ ] Play a song in Spotify → the bottom pane shows title, progress and synced lyrics within a few seconds.
- [ ] Click the music pane, press `+`/`-` to nudge lyric timing, `space` to pause.
- [ ] Spotify: black/grey interface, a **VOID** entry in the left sidebar.
- [ ] Left monitor: a monochrome VOID wallpaper too, matching the right one; `void wallpaper verify` says
      "Plasma shows the VOID wallpaper on every monitor".
- [ ] Kitty: black/grey, `Ctrl+Shift+L` opens the lyrics view.
- [ ] After logging out and in: Meta+Alt+L opens VOID lyrics, Meta+Alt+D toggles the dashboard.

If the dashboard window isn't on the right monitor or has a border, log out and back in once
(KWin then reads the new window rule), then `void launch`.

## 8. Daily use

```bash
void launch          # open the dashboard (won't open a second one)
void stop            # close it and stop void-core
void profile minimal | balanced | showcase
void music           # lyrics view in any terminal
void autostart on    # open the dashboard at login while VOID is active
```

Inside the dashboard: `Ctrl+B r` restarts all panes, `Ctrl+B d` detaches.

## 9. After a Spotify update

Spotify updates remove Spicetify themes (that's how Spicetify works). `void health` tells you;
fix with:

```bash
void spotify apply
```

If that fails, Spicetify doesn't support the new Spotify yet: `spicetify upgrade`, then retry.

## 10. Switching back (to Crimson or your previous desktop)

```bash
void deactivate      # exactly what you had before activating — Crimson's look, services,
                     # Konsole default, wallpaper and Spotify theme come back
void activate        # switch to VOID again, any time
```

Give VOID up completely:

```bash
void restore --uninstall    # desktop as before VOID was ever activated + VOID's files removed
rm -rf ~/Projects/void      # optional, afterwards
```

Packages installed in step 3 are not removed automatically (other software may use them); they're
listed in `~/.local/state/void-desktop/installed-packages.txt`.

---

Problems: [TROUBLESHOOTING.md](TROUBLESHOOTING.md) · how switching and backups work:
[SWITCHING.md](SWITCHING.md) · what was tested: [TESTING.md](TESTING.md).
