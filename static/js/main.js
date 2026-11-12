// Entry point: wires the modules together and loads the server's region info.

import { $, setStatus, store } from "./util.js";
import { state, syncLegs } from "./state.js";
import { initMap, map, refreshBasemap, setBasemap } from "./map.js";
import { initNet } from "./online.js";
import { initUpdate } from "./update.js";
import { initStops, renderMarkers, renderStops } from "./stops.js";
import { initStyle, renderProfiles, renderStyle } from "./style.js";
import { initPois } from "./pois.js";
import { initOverlays } from "./overlays.js";
import { renderMarkerPanel } from "./markerPanel.js";
import { fetchRoute, initRoute } from "./route.js";
import { initFuel } from "./fuel.js";
import { initGpx } from "./gpx.js";
import { readHash, writeHash } from "./hash.js";

function setTheme(theme, save = false) {
  document.documentElement.dataset.theme = theme;
  document.querySelector('meta[name="theme-color"]').content = theme === "dark" ? "#202124" : "#ffffff";
  if (save) store.set("ui.theme", theme);
  if (state.info) refreshBasemap();
}

export function update({ fit = false } = {}) {
  syncLegs();
  renderProfiles();
  renderStops();
  renderMarkers();
  renderStyle();
  writeHash();
  fetchRoute({ fit });
}

(async function init() {
  initNet();
  initMap();
  initStyle();
  initStops();
  initPois();
  initOverlays();
  renderMarkerPanel();
  initRoute();
  initFuel();
  initGpx();

  setTheme(document.documentElement.dataset.theme === "light" ? "light" : "dark");
  $("theme-toggle").addEventListener("click", () =>
    setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark", true));

  try {
    state.info = await (await fetch("/api/region")).json();
  } catch {
    setStatus("Couldn't reach the GravelMaps server.", true);
    return;
  }
  readHash();
  setBasemap(state.basemap); // again, now that the road-tile version is known
  renderProfiles();
  const [s, w, n, e] = state.info.bbox;
  if (!state.stops.some(Boolean)) map.fitBounds([[s, w], [n, e]], { padding: [20, 20] });
  const names = state.info.regions.map((r) => r.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()));
  $("regions").textContent = `Map data © OpenStreetMap contributors · ${names.join(", ")}`;
  update({ fit: state.stops.some(Boolean) });
  showPendingSetup();
  initUpdate();
})();

// After an upgrade (or a setup cut short) some data may still be missing, like the offline map.
async function showPendingSetup() {
  try {
    const { pending } = await (await fetch("/api/setup/status")).json();
    if (!pending.length) return;
    $("setup-note").innerHTML = `Not downloaded yet: ${pending.join(", ").toLowerCase()}. You need it to use GravelMaps offline. <b>Download it</b>`;
    $("setup-note").hidden = false;
  } catch { /* the note is optional */ }
}
