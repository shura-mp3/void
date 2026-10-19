// Fake Plasma desktop-scripting API for tests: state in $HOME/plasma-desktops.json
const fs = require("fs");
const file = process.env.HOME + "/plasma-desktops.json";
const state = JSON.parse(fs.readFileSync(file, "utf8"));
const out = [];
function makeDesktop(d) {
	let group = [];
	const obj = {
		get screen() { return d.screen; },
		get wallpaperPlugin() { return d.plugin; },
		set wallpaperPlugin(v) { d.plugin = v; },
		set currentConfigGroup(g) { group = g; },
		get currentConfigGroup() { return group; },
		readConfig(k, def) { const c = d.config[group.join("/")] || {}; return k in c ? c[k] : def; },
		writeConfig(k, v) { const g = group.join("/"); (d.config[g] = d.config[g] || {})[k] = v; },
	};
	return obj;
}
const sandbox = {
	desktopsForActivity: () => state.desktops.map(makeDesktop),
	desktops: () => state.desktops.map(makeDesktop),
	currentActivity: () => "act-1",
	screenGeometry: (i) => state.screens[i],
	print: (s) => out.push(String(s)),
};
new Function(...Object.keys(sandbox), process.argv[2])(...Object.values(sandbox));
fs.writeFileSync(file, JSON.stringify(state, null, 1));
process.stdout.write(out.join("\n") + "\n");
