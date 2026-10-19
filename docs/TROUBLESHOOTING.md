# Troubleshooting

Start with `void health` (problems) and `void status` (state).

| symptom | cause / fix |
|---|---|
| `void activate` stopped with an error | state is `failed`, and everything applied so far is journaled. Fix the cause, then `void activate` (continues) or `void deactivate` (undoes) |
| dashboard opens on the wrong monitor | `void monitors` shows what KScreen reports. Pin it: `[dashboard] monitor = "HDMI-A-1"` in `~/.config/void-desktop/config.toml`, then `void activate` (rewrites the KWin rule) |
| dashboard window is a normal window | VOID isn't active (the KWin rule only exists while it is), or the window title isn't `VOID//DASHBOARD` (Konsole: Settings → Edit Current Profile → Tabs). Check System Settings → Window Management → Window Rules → "VOID dashboard…" |
| btop pane says "terminal size too small" | the window is under 80×24 cells for that pane. Lower `dashboard_font_size` in `config/tokens.toml`, `void tokens build`, `void konsole apply`; or `Ctrl+B r` |
| a pane shows "… exited — restarting" | the program crashed; it restarts with backoff. `Ctrl+C` in that pane stops it; `Ctrl+B r` restarts all |
| music pane: VOID-CORE OFFLINE | `void launch` starts void-core; logs: `journalctl --user -u void-core -f` |
| no lyrics for a track | LRCLIB has no synced lyrics for it. Drop `Artist - Title.lrc` into `~/.config/void-desktop/lyrics/`, then `r` in the music pane |
| lyrics early/late | `+` / `-` in the music pane (saved per track), or `[lyrics] latency_ms` globally |
| Spotify lost the theme | Spotify updated, which replaces Spicetify's patch: `void spotify apply`. If apply fails, Spicetify doesn't support the new Spotify yet: `spicetify upgrade`, then retry |
| VOID page in Spotify: "theme script is not active" | `inject_theme_js` is off: `void spotify apply` |
| Konsole still opens Crimson OS / the old profile | close **all** Konsole windows once; Konsole reads its default profile at start |
| want a plain shell in Konsole | `VOID_PLAIN=1 konsole`, or pick another profile in Konsole's New Tab menu |
| colours changed on the left monitor too | expected: KDE colour schemes are global. Only the dashboard is right-monitor-only (both monitors get VOID wallpapers) |
| two Spotify watchers / duplicate processes | `void health` reports them. `void stop`, then `void launch` |
| something else changed my KDE settings and deactivate "kept" it | that's the safety rule (your newer value wins). `void deactivate --force` reverts it anyway |
| I want the pre-VOID desktop back, completely | `void restore` (add `--uninstall` to remove VOID's files) |
| left monitor kept its old wallpaper | VOID before this update set the right one only: run `void activate` again (safe; it adds the left monitor). Check with `void wallpaper verify` |
| wallpaper choice for one side | `[wallpaper] pick_left` / `pick_right` in config.toml, then `void activate` |
| Meta+Alt+L still opens Crimson's lyrics | KDE reads global shortcuts at login: log out and back in. System Settings → Shortcuts shows "VOID Lyrics" |
| Kitty still looks like Crimson | open a new Kitty window, or `Ctrl+Shift+F5`; check the last lines of `~/.config/kitty/kitty.conf` hold VOID's block |
