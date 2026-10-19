// VOID Spotify — theme script (injected by Spicetify when inject_theme_js = 1)
//
// 1. Opens ONE loopback WebSocket to void-core (ws://127.0.0.1:47812) and exposes it as
//    window.VoidBridge for the "VOID" custom app. void-core is the single source of lyrics,
//    offsets and spectrum shared with the terminal dashboard (nothing is fetched twice).
// 2. Mirrors VOID's performance profile and the grayscale-artwork setting onto <html> classes,
//    so user.css can react live without restarting Spotify.
// Without void-core Spotify is unaffected: the bridge retries with backoff (2 s .. 60 s).

(function VoidTheme() {
	if (!window.Spicetify || !Spicetify.Player || !Spicetify.LocalStorage) {
		setTimeout(VoidTheme, 300);
		return;
	}
	if (window.VoidBridge) return;

	const PORT = parseInt(Spicetify.LocalStorage.get("void:bridge-port") || "47812", 10);
	const URL = `ws://127.0.0.1:${PORT}`;
	const CLASSES = ["void-profile-minimal", "void-profile-balanced", "void-profile-showcase", "void-reduce-effects", "void-grayscale-art"];

	const bridge = new EventTarget();
	bridge.state = { connected: false, player: null, lyrics: null, ui: null };
	bridge.wanted = new Map(); // topic -> refcount
	let ws = null;
	let backoff = 2000;

	bridge.send = (obj) => {
		if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
	};
	const pushTopics = () => bridge.send({ cmd: "sub", topics: [...bridge.wanted.keys()] });
	bridge.want = (topic) => {
		bridge.wanted.set(topic, (bridge.wanted.get(topic) || 0) + 1);
		pushTopics();
	};
	bridge.unwant = (topic) => {
		const n = (bridge.wanted.get(topic) || 1) - 1;
		if (n <= 0) bridge.wanted.delete(topic);
		else bridge.wanted.set(topic, n);
		pushTopics();
	};
	bridge.offset = (delta) => bridge.send(delta === "reset" ? { cmd: "offset", reset: true } : { cmd: "offset", delta });

	function applyUi(ui) {
		const root = document.documentElement;
		root.classList.remove(...CLASSES);
		if (!ui) return;
		const prof = ui.effective_performance || "balanced";
		root.classList.add(`void-profile-${prof}`);
		if (prof === "minimal" || ui.gamemode) root.classList.add("void-reduce-effects");
		const local = Spicetify.LocalStorage.get("void:grayscale-art"); // per-Spotify override: "1" / "0"
		if (local === "1" || (local !== "0" && ui.grayscale_art)) root.classList.add("void-grayscale-art");
	}

	function connect() {
		try {
			ws = new WebSocket(URL);
		} catch (e) {
			return schedule();
		}
		ws.onopen = () => {
			backoff = 2000;
			bridge.state.connected = true;
			pushTopics();
			bridge.dispatchEvent(new CustomEvent("status", { detail: true }));
		};
		ws.onmessage = (ev) => {
			let msg;
			try {
				msg = JSON.parse(ev.data);
			} catch (e) {
				return;
			}
			const t = msg.t;
			if (t === "player" || t === "lyrics" || t === "ui") bridge.state[t] = msg;
			if (t === "ui") applyUi(msg);
			bridge.dispatchEvent(new CustomEvent(t, { detail: msg }));
		};
		ws.onclose = () => {
			const was = bridge.state.connected;
			bridge.state.connected = false;
			if (was) bridge.dispatchEvent(new CustomEvent("status", { detail: false }));
			schedule();
		};
		ws.onerror = () => {}; // onclose follows
	}
	function schedule() {
		setTimeout(connect, backoff);
		backoff = Math.min(backoff * 2, 60000);
	}

	window.VoidBridge = bridge;
	connect();
})();
