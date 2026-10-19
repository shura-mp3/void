// Headless-Chromium check of VOID's Spotify code: the REAL theme.js and VOID custom app run in a page
// served as https://xpui.app.spotify.com (Spotify's UI origin) with a mocked Spicetify API, talking to
// the REAL void-core bridge. Usage (see run_spotify_page_check.py):
//   NODE_PATH=<dir with react, react-dom, playwright-core> node spotify_page.js <bridge-port> <screenshot.png>
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright-core");

const ROOT = path.resolve(__dirname, "../..");
const port = process.argv[2];
const shot = process.argv[3];
const nm = process.env.NODE_PATH.split(":")[0];
const colors = fs.readFileSync(path.join(ROOT, "spicetify/Themes/VOID/color.ini"), "utf8");
const vars = [...colors.matchAll(/^([\w-]+)\s*=\s*([0-9A-F]{6})$/gm)].map(([, k, v]) => {
	const rgb = [0, 2, 4].map((i) => parseInt(v.slice(i, i + 2), 16)).join(",");
	return `--spice-${k}: #${v}; --spice-rgb-${k}: ${rgb};`;
}).join("\n");

const html = `<!doctype html><html><head><meta charset="utf-8"><style>
:root { ${vars} } html, body { margin: 0; background: var(--spice-main); font-family: sans-serif; }
</style></head><body><div id="root" style="width:1200px"></div>
<script src="/react.js"></script><script src="/react-dom.js"></script>
<script>
const t0 = Date.now();
const listeners = {};
window.Spicetify = {
  React, ReactDOM,
  LocalStorage: (() => { const m = { "void:bridge-port": "${port}" }; return { get: (k) => m[k] ?? null, set: (k, v) => (m[k] = v) }; })(),
  Player: {
    data: { item: { uri: "spotify:track:demo1", name: "Everything You Are", artists: [{ name: "Void Test" }],
                    album: { name: "Signal Lost" }, metadata: {} } },
    getProgress: () => 4700 + 0 * (Date.now() - t0),   // frozen at 4.7 s: "You could …"
    getDuration: () => 30000,
    isPlaying: () => true,
    addEventListener: (e, f) => (listeners[e] = f), removeEventListener: () => {},
  },
};
</script>
<script src="/theme.js"></script><script src="/index.js"></script>
<script>ReactDOM.createRoot(document.getElementById("root")).render(render());</script>
</body></html>`;

const files = {
	"/react.js": path.join(nm, "react/umd/react.production.min.js"),
	"/react-dom.js": path.join(nm, "react-dom/umd/react-dom.production.min.js"),
	"/theme.js": path.join(ROOT, "spicetify/Themes/VOID/theme.js"),
	"/index.js": path.join(ROOT, "spicetify/CustomApps/void/index.js"),
};

(async () => {
	const browser = await chromium.launch({ executablePath: process.env.CHROMIUM || "/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell" });
	const page = await browser.newPage({ viewport: { width: 1240, height: 760 } });
	const errors = [];
	page.on("pageerror", (e) => errors.push(String(e)));
	await page.route("https://xpui.app.spotify.com/**", (route) => {
		const p = new URL(route.request().url()).pathname;
		if (files[p]) return route.fulfill({ contentType: "text/javascript", body: fs.readFileSync(files[p]) });
		return route.fulfill({ contentType: "text/html", body: html });
	});
	await page.goto("https://xpui.app.spotify.com/index.html");
	const result = {};
	await page.waitForFunction(() => document.body.innerText.includes("CORE LINKED"), null, { timeout: 15000 });
	await page.waitForFunction(() => document.body.innerText.includes("WORD SYNC"), null, { timeout: 15000 });
	result.linked = true;
	result.text = await page.evaluate(() => document.body.innerText);
	result.htmlClass = await page.evaluate(() => document.documentElement.className);
	result.current = await page.evaluate(() => document.querySelector(".void-current")?.innerText);
	result.currentColours = await page.evaluate(() => [...document.querySelectorAll(".void-current span")].map((s) => getComputedStyle(s).color));
	await page.click("text=+100");
	await page.waitForFunction(() => document.body.innerText.includes("OFFSET +100 MS"), null, { timeout: 5000 });
	result.offsetShown = true;
	await page.click("text=0");
	await page.screenshot({ path: shot });
	result.errors = errors;
	console.log(JSON.stringify(result));
	await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
