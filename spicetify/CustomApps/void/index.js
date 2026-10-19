// VOID — Spicetify custom app (sidebar page): now playing, synced lyrics, spectrum.
//
// Lyrics, offsets and the spectrum come from void-core through the theme's bridge
// (window.VoidBridge): the same local .lrc → cache → LRCLIB result the terminal dashboard shows,
// so nothing is looked up twice. Position comes from Spotify itself (Spicetify.Player), which is
// more precise than MPRIS. Colours are the theme's --spice-* variables (from VOID's tokens).
// Word highlighting appears only when the LRC really has word timestamps.

const react = Spicetify.React;
const { useState, useEffect, useRef, useCallback } = react;
const h = react.createElement;

// void-muted is VOID's own color.ini key; Spotify's subtext grey stands in if Spicetify doesn't export it
const V = (name) => (name === "void-muted" ? "var(--spice-void-muted, var(--spice-subtext))" : `var(--spice-${name})`);
const MONO = '"JetBrains Mono", "DejaVu Sans Mono", monospace';

const STYLE = `
.void-app { min-height: 100%; padding: 28px 36px 44px; box-sizing: border-box; color: ${V("text")}; background: ${V("main")}; }
.void-panel { position: relative; border: 1px solid ${V("border-inactive")}; background: ${V("main-elevated")}; padding: 18px 22px; }
.void-label { font-family: ${MONO}; font-size: 10px; letter-spacing: .12em; text-transform: uppercase; color: ${V("subtext")}; }
.void-btn { font-family: ${MONO}; font-size: 10px; letter-spacing: .08em; color: ${V("text")}; background: transparent;
  border: 1px solid ${V("border-inactive")}; padding: 6px 10px; cursor: pointer; transition: border-color 120ms, color 120ms; }
.void-btn:hover { border-color: ${V("accent-active")}; color: ${V("accent-active")}; }
.void-btn:focus-visible { outline: 1px solid ${V("accent-active")}; outline-offset: 2px; }
.void-btn:disabled { opacity: .4; cursor: default; }
.void-current { color: ${V("accent-active")}; font-weight: 700; line-height: 1.1; letter-spacing: -0.01em; transition: opacity 200ms; }
.void-reduce-effects .void-current { transition: none; }
.void-dim { color: ${V("void-muted")}; }
.void-near { color: ${V("subtext")}; }
`;

function trackId(x) {
	if (!x) return "";
	const parts = String(x).split(/[/:]/);
	return parts[parts.length - 1];
}
function lineIndex(lines, t) {
	let lo = 0, hi = lines.length - 1, ans = -1;
	while (lo <= hi) {
		const mid = (lo + hi) >> 1;
		if (lines[mid].t <= t) { ans = mid; lo = mid + 1; } else hi = mid - 1;
	}
	return ans;
}
function wordIndex(line, t) {
	if (!line || !line.w) return -1;
	let n = -1;
	for (let i = 0; i < line.w.length; i++) if (line.w[i][0] <= t) n = i;
	return n;
}
function fmt(ms) {
	const s = Math.max(0, Math.floor(ms / 1000));
	return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
function spotifyTrack() {
	const item = Spicetify.Player.data?.item;
	if (!item) return null;
	const md = item.metadata || {};
	return {
		uri: item.uri,
		title: item.name || md.title || "",
		artist: (item.artists || []).map((a) => a.name).join(", ") || md.artist_name || "",
		album: item.album?.name || md.album_title || "",
		art: md.image_xlarge_url || md.image_large_url || md.image_url || item.album?.images?.[0]?.url || "",
		duration: Spicetify.Player.getDuration ? Spicetify.Player.getDuration() : item.duration?.milliseconds || 0,
	};
}

function useBridge() {
	const bridge = window.VoidBridge;
	const [state, setState] = useState(() => ({ ...(bridge?.state || {}) }));
	useEffect(() => {
		if (!bridge) return;
		const update = () => setState({ ...bridge.state });
		const events = ["status", "player", "lyrics", "ui"];
		events.forEach((e) => bridge.addEventListener(e, update));
		return () => events.forEach((e) => bridge.removeEventListener(e, update));
	}, [bridge]);
	return [bridge, state];
}

function Spectrum({ bridge }) {
	const canvas = useRef(null);
	useEffect(() => {
		if (!bridge) return;
		let frame = null, pending = null;
		const css = getComputedStyle(document.documentElement);
		const col = (n) => `rgb(${css.getPropertyValue(`--spice-rgb-${n}`).trim() || "200,200,200"})`;
		const draw = () => {
			frame = null;
			const c = canvas.current;
			if (!c || !pending) return;
			const ctx = c.getContext("2d");
			const w = (c.width = c.clientWidth * devicePixelRatio), hgt = (c.height = c.clientHeight * devicePixelRatio);
			ctx.clearRect(0, 0, w, hgt);
			const n = pending.length, bw = w / n;
			for (let i = 0; i < n; i++) {
				const v = pending[i] / 255;
				const bh = Math.max(1, v * hgt * 0.95);
				ctx.fillStyle = v > 0.75 ? col("accent-active") : v > 0.4 ? col("subtext") : col("border-inactive");
				ctx.fillRect(i * bw + bw * 0.2, hgt - bh, bw * 0.6, bh);
			}
		};
		const onSpec = (e) => {
			pending = e.detail.b;
			if (!frame) frame = requestAnimationFrame(draw);
		};
		bridge.addEventListener("spec", onSpec);
		bridge.want("spec"); // void-core runs CAVA only while someone wants it AND music plays
		const onVis = () => (document.hidden ? bridge.unwant("spec") : bridge.want("spec"));
		document.addEventListener("visibilitychange", onVis);
		return () => {
			bridge.removeEventListener("spec", onSpec);
			document.removeEventListener("visibilitychange", onVis);
			if (!document.hidden) bridge.unwant("spec");
			if (frame) cancelAnimationFrame(frame);
		};
	}, [bridge]);
	return h("div", { className: "void-panel", style: { height: 96, marginTop: 16 } },
		h("div", { className: "void-label", style: { position: "absolute", top: 8, left: 14 } }, "06 // SPECTRUM · CAVA"),
		h("canvas", { ref: canvas, style: { width: "100%", height: "100%", display: "block" } }));
}

function Lyrics({ lyrics, matched, connected, track, position, wordMode }) {
	const status = lyrics?.status;
	const big = (text, sub) => h("div", { style: { textAlign: "center", padding: "56px 0" } },
		h("div", { className: "void-current", style: { fontSize: 44 } }, text),
		sub && h("div", { className: "void-label", style: { marginTop: 14 } }, sub));

	if (!connected) return big("VOID-CORE OFFLINE", "start it: void launch   ·   Spotify keeps working without it");
	if (!track) return big("AWAITING SIGNAL", "press play");
	if (!matched || status === "loading") return big("SEARCHING", "local .lrc → cache → lrclib.net");
	if (status === "instrumental") return big("INSTRUMENTAL", track.artist);
	if (status === "ad") return big("ADVERTISEMENT");
	if (status === "error")
		return big("LYRICS UNREACHABLE", `${(lyrics.error || "network error").slice(0, 90)} · ` +
			(lyrics.retry_in ? `retrying in ${lyrics.retry_in}s` : "press r in `void music` to retry"));
	if (status === "plain") return big(track.title, "unsynced lyrics only — no timing is invented");
	if (status !== "synced" || !lyrics.lines?.length) return big(track.title, "no synced lyrics · add an .lrc to ~/.config/void-desktop/lyrics/");

	const lines = lyrics.lines;
	const t = position + (lyrics.offset_ms || 0);
	const idx = lineIndex(lines, t);
	const cur = idx >= 0 ? lines[idx] : null;
	const wi = wordIndex(cur, t);
	const text = (i) => (i >= 0 && i < lines.length ? lines[i].text || "♪" : "");

	let current;
	if (!cur) current = "· · ·";
	else if (wordMode && cur.w) current = (cur.w[Math.max(0, wi)][1] || "").trim();
	else if (cur.w) current = cur.w.map((w, i) => h("span", { key: i, style: { color: i <= wi ? V("accent-active") : V("void-muted") } }, w[1]));
	else current = text(idx);

	return h("div", { style: { textAlign: "center", padding: "28px 0" } },
		h("div", { className: "void-dim", style: { fontSize: 22, minHeight: 30 } }, text(idx - 1)),
		h("div", { key: wordMode ? `w${idx}-${wi}` : `l${idx}`, className: "void-current",
			style: { fontSize: wordMode && cur?.w ? 96 : 52, margin: "16px 0", minHeight: 64 } }, current),
		h("div", { className: "void-near", style: { fontSize: 26 } }, text(idx + 1)),
		h("div", { className: "void-dim", style: { fontSize: 22, marginTop: 6 } }, text(idx + 2)));
}

function VoidApp() {
	const [bridge, bstate] = useBridge();
	const [track, setTrack] = useState(spotifyTrack);
	const [position, setPosition] = useState(() => Spicetify.Player.getProgress());
	const [playing, setPlaying] = useState(() => Spicetify.Player.isPlaying());
	const [wordMode, setWordMode] = useState(() => Spicetify.LocalStorage.get("void:word-mode") === "1");

	useEffect(() => {
		const onSong = () => { setTrack(spotifyTrack()); setPosition(Spicetify.Player.getProgress()); };
		const onPlay = () => { setPlaying(Spicetify.Player.isPlaying()); setPosition(Spicetify.Player.getProgress()); };
		Spicetify.Player.addEventListener("songchange", onSong);
		Spicetify.Player.addEventListener("onplaypause", onPlay);
		return () => {
			Spicetify.Player.removeEventListener("songchange", onSong);
			Spicetify.Player.removeEventListener("onplaypause", onPlay);
		};
	}, []);
	useEffect(() => {
		// lyric clock: 20 Hz only while this page is open and music plays
		if (!playing) return;
		const id = setInterval(() => !document.hidden && setPosition(Spicetify.Player.getProgress()), 50);
		return () => clearInterval(id);
	}, [playing]);

	const toggleMode = useCallback(() => {
		setWordMode((m) => { Spicetify.LocalStorage.set("void:word-mode", m ? "0" : "1"); return !m; });
	}, []);

	const lyrics = bstate.lyrics;
	const coreTrack = bstate.player?.track;
	const matched = !!(track && lyrics && (trackId(lyrics.track_id) === trackId(track.uri) ||
		(coreTrack && coreTrack.title === track.title && trackId(coreTrack.id) === trackId(lyrics.track_id))));
	const hasWords = !!lyrics?.has_words;
	const ui = bstate.ui || {};

	return h("div", { className: "void-app" },
		h("style", null, STYLE),
		h("div", { className: "void-panel", style: { display: "flex", gap: 22, alignItems: "center" } },
			track?.art && h("img", { className: "void-art", src: track.art, alt: "", style: { width: 112, height: 112, objectFit: "cover", border: `1px solid ${V("border-inactive")}` } }),
			h("div", { style: { flex: 1, minWidth: 0 } },
				h("div", { className: "void-label" },
					`05 // NOW PLAYING · ${playing ? "LIVE" : "HOLD"} · CORE ${bstate.connected ? "LINKED" : "OFFLINE"}` +
					(ui.effective_performance ? ` · ${String(ui.effective_performance).toUpperCase()}` : "")),
				h("div", { style: { fontSize: 34, fontWeight: 700, color: V("accent-active"), lineHeight: 1.2, margin: "6px 0", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" } },
					track?.title || "—"),
				h("div", { style: { color: V("text") } }, track?.artist || ""),
				h("div", { style: { fontFamily: MONO, fontSize: 12, color: V("subtext"), marginTop: 2 } },
					(track?.album || "") + (track ? `  ·  ${fmt(position)} / ${fmt(track.duration)}` : ""))),
			h("div", { style: { display: "flex", flexDirection: "column", gap: 6, alignItems: "flex-end" } },
				h("div", { className: "void-label" },
					lyrics?.status === "synced" ? `${hasWords ? "WORD" : "LINE"} SYNC · ${(lyrics.source || "").toUpperCase()}` : (lyrics?.status || "").toUpperCase()),
				h("div", { className: "void-label" }, `OFFSET ${(lyrics?.user_offset_ms || 0) >= 0 ? "+" : ""}${lyrics?.user_offset_ms || 0} MS`),
				h("div", { style: { display: "flex", gap: 6 } },
					h("button", { className: "void-btn", title: "lyrics later (-100 ms)", disabled: !bstate.connected, onClick: () => bridge.offset(-100) }, "−100"),
					h("button", { className: "void-btn", title: "reset this track's offset", disabled: !bstate.connected, onClick: () => bridge.offset("reset") }, "0"),
					h("button", { className: "void-btn", title: "lyrics earlier (+100 ms)", disabled: !bstate.connected, onClick: () => bridge.offset(100) }, "+100")),
				hasWords && h("button", { className: "void-btn", onClick: toggleMode }, wordMode ? "LINE MODE" : "WORD MODE"))),
		h("div", { className: "void-panel", style: { marginTop: 16 } },
			h("div", { className: "void-label" }, "04 // LYRICS.SYS"),
			h(Lyrics, { lyrics, matched, connected: bstate.connected, track, position, wordMode: wordMode && hasWords })),
		bstate.connected && ui.perf?.spectrum !== false && h(Spectrum, { bridge }));
}

function render() {
	if (!window.VoidBridge) {
		return h("div", { style: { padding: 40, color: V("text"), fontFamily: MONO } },
			"The VOID theme script is not active. Run: void spotify apply  (it sets inject_theme_js = 1).");
	}
	return h(VoidApp);
}
