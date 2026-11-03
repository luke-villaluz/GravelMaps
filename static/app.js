"use strict";

// Display info per road kind; keys match the server's KINDS. Order = legend order.
const KINDS = {
  unpaved: { label: "Dirt / Gravel", color: "--k-unpaved" },
  rough: { label: "Rough / 4x4", color: "--k-rough", dash: "6 5" },
  trail: { label: "Singletrack / OHV", color: "--k-trail", dash: "2 6" },
  unknown: { label: "Surface Unknown", color: "--k-unknown" },
  paved: { label: "Paved", color: "--k-paved" },
  major: { label: "Major Road", color: "--k-major" },
  highway: { label: "Highway", color: "--k-highway" },
};
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const $ = (id) => document.getElementById(id);
const store = {
  get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
};

const state = {
  stops: [null, null], // each: {lat, lon, label} or null
  legs: [], // slider values per leg (arrays in server kind order)
  vehicles: ["car"], // vehicle per leg, e.g. drive the car in, then ride the bike
  activeLeg: 0,
  route: null,
  basemap: store.get("ui.basemap") || "satellite",
  info: null, // /api/region: profiles, kinds, presets
};

// ---------- map ----------
// Explicit zoom limits: otherwise Leaflet borrows them from tile layers, and while basemaps are
// swapped the dirt overlay's minZoom of 13 briefly becomes the map's and yanks the view in.
const map = L.map("map", { zoomControl: false, minZoom: 3, maxZoom: 19 }).setView([39.5, -117], 6);
L.control.scale({ imperial: true, metric: false, position: "bottomleft" }).addTo(map);
map.attributionControl.setPrefix(false);

const esri = (svc) => `https://server.arcgisonline.com/ArcGIS/rest/services/${svc}/MapServer/tile/{z}/{y}/{x}`;
// Road overlays rendered by our server from the routing graph (see gravelmaps/tiles.py).
const roadLayer = (layer, theme, minZoom, zIndex) =>
  L.tileLayer(`/api/roads/${layer}/{z}/{x}/{y}.png?theme=${theme}&v=${state.info?.tile_version || 0}`, { minZoom, maxZoom: 19, zIndex, pane: "roads" });
const BASEMAPS = {
  map: {
    label: "Map",
    layers: () => [
      L.tileLayer(esri("World_Street_Map"), { maxZoom: 19, attribution: "Basemap © Esri, HERE, Garmin, © OpenStreetMap contributors" }),
      roadLayer("main", "dark", 6, 6),
    ],
  },
  satellite: {
    label: "Satellite",
    layers: () => [
      L.tileLayer(esri("World_Imagery"), { maxZoom: 19, attribution: "Imagery © Esri, Maxar, Earthstar Geographics" }),
      L.tileLayer(esri("Reference/World_Transportation"), { maxZoom: 19, opacity: 0.95 }),
      L.tileLayer(esri("Reference/World_Boundaries_and_Places"), { maxZoom: 19 }),
    ],
  },
  topo: {
    label: "Topo",
    layers: () => [
      L.tileLayer("https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
        { maxZoom: 17, attribution: "© OpenStreetMap contributors, SRTM · © OpenTopoMap (CC-BY-SA)" }),
      roadLayer("main", "dark", 6, 6),
    ],
  },
};
// Own pane, above the basemap and outside its contrast filter, so the overlay keeps its own colors.
map.createPane("roads").style.zIndex = 250;
const baseGroup = L.layerGroup().addTo(map);

// Saved only on a click, so changing the default later reaches everyone who never picked one.
function setBasemap(key, save = false) {
  if (!BASEMAPS[key]) key = "satellite";
  state.basemap = key;
  if (save) store.set("ui.basemap", key);
  $("map").dataset.base = key;
  baseGroup.clearLayers();
  BASEMAPS[key].layers().forEach((l) => baseGroup.addLayer(l));
  // Subdued dirt-road detail for close-up looks; the basemaps leave most of these out.
  baseGroup.addLayer(roadLayer("dirt", key === "satellite" ? "light" : "dark", 12, 5));
  $("basemaps").querySelectorAll("button[data-key]").forEach((b) => b.classList.toggle("on", b.dataset.key === key));
}
for (const [key, b] of Object.entries(BASEMAPS)) {
  const btn = document.createElement("button");
  btn.textContent = b.label;
  btn.dataset.key = key;
  btn.addEventListener("click", () => setBasemap(key, true));
  $("basemaps").appendChild(btn);
}
setBasemap(state.basemap);

$("zoom-in").addEventListener("click", () => map.zoomIn());
$("zoom-out").addEventListener("click", () => map.zoomOut());
const showZoom = () => { $("zoom-level").textContent = `Z${Math.round(map.getZoom())}`; };
map.on("zoomend", showZoom);
showZoom();

// Inactive legs render into their own pane, faded as a whole so overlapping line caps don't stack.
for (const [name, z] of [["routeInactive", 410], ["routeActive", 420]]) map.createPane(name).style.zIndex = z;
map.getPane("routeInactive").style.opacity = 0.4;
const renderers = { routeInactive: L.svg({ pane: "routeInactive" }), routeActive: L.svg({ pane: "routeActive" }) };
const routeLayer = L.featureGroup().addTo(map);
// Stretches longer than the fuel range: a red band under the route.
map.createPane("fuelShort").style.zIndex = 405;
const fuelShortLayer = L.layerGroup().addTo(map);
const markerLayer = L.layerGroup().addTo(map);
let meMarker = null;

// ---------- helpers ----------
const fmtDist = (m) => {
  const mi = m / 1609.344;
  return mi < 0.1 ? `${Math.round(m * 3.28084)} ft` : mi < 10 ? `${mi.toFixed(1)} mi` : `${Math.round(mi)} mi`;
};
const fmtTime = (s) => {
  const h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60);
  return h ? `${h} hr ${m} min` : `${m} min`;
};
const fmtTimeShort = (s) => {
  const h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m`;
};
const fmtLL = (lat, lon) => `${lat.toFixed(5)}, ${lon.toFixed(5)}`;
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function setStatus(msg, isError = false) {
  const el = $("status");
  el.hidden = !msg;
  el.textContent = msg || "";
  el.classList.toggle("error", isError);
}

const stopRole = (i) => (i === 0 ? "start" : i === state.stops.length - 1 ? "end" : "via");
const stopLetter = (i) => (i === 0 ? "A" : i === state.stops.length - 1 ? "B" : String(i));

// ---------- legs (per-leg route style) ----------
const kindKeys = () => state.info.kinds.map((k) => k.key);
const presetValues = (key) => [...state.info.presets[key].values];
const defaultLeg = () => presetValues(state.info.default_preset);
const presetFits = (key, vehicle) => !state.info.presets[key].vehicles || state.info.presets[key].vehicles.includes(vehicle);
const presetOf = (values) =>
  Object.keys(state.info.presets).find((k) => state.info.presets[k].values.every((v, i) => v === values[i])) || null;

function syncLegs() {
  const n = Math.max(1, state.stops.length - 1);
  while (state.legs.length < n) state.legs.push([...(state.legs[state.legs.length - 1] || defaultLeg())]);
  state.legs.length = n;
  while (state.vehicles.length < n) state.vehicles.push(state.vehicles[state.vehicles.length - 1] || "car");
  state.vehicles.length = n;
  state.activeLeg = Math.min(state.activeLeg, n - 1);
}

function insertStop(i, stop) {
  // A new stop splits leg i-1 in two; both halves keep its style.
  state.stops.splice(i, 0, stop);
  state.legs.splice(i - 1, 0, [...state.legs[i - 1]]);
  state.vehicles.splice(i - 1, 0, state.vehicles[i - 1]);
}

function removeStop(i) {
  state.stops.splice(i, 1);
  for (const arr of [state.legs, state.vehicles]) {
    if (i === 0) arr.shift();
    else arr.splice(i, 1); // merge legs i-1 and i, keeping i-1's style and vehicle
  }
  if (state.stops.length < 2) state.stops.push(null);
  update();
}

function sliderWord(v) {
  if (v === 0) return "Never";
  if (v <= 25) return "Avoid";
  if (v <= 45) return "Less";
  if (v <= 55) return "Neutral";
  if (v <= 75) return "More";
  return "Prefer";
}

function renderStyle() {
  const legs = state.legs;
  const multi = legs.length > 1;
  const active = legs[state.activeLeg];

  const tabs = $("legs");
  tabs.hidden = !multi;
  $("apply-all").hidden = !multi;
  tabs.innerHTML = "";
  if (multi) {
    legs.forEach((v, i) => {
      const b = document.createElement("button");
      b.classList.toggle("on", i === state.activeLeg);
      const leg = state.route?.legs?.[i];
      const preset = presetOf(v);
      const sub = leg ? `${fmtDist(leg.distance_m)} · ${fmtTimeShort(leg.duration_s)}` : (preset ? state.info.presets[preset].label : "Custom");
      b.innerHTML = `<b>${PROFILE_ICONS[state.vehicles[i]] || ""}${stopLetter(i)} → ${stopLetter(i + 1)}</b><small>${esc(sub)}</small>`;
      b.addEventListener("click", () => { state.activeLeg = i; renderProfiles(); renderStyle(); renderRoute(); });
      tabs.appendChild(b);
    });
  }

  const chips = $("presets");
  chips.innerHTML = "";
  const current = presetOf(active);
  for (const [key, p] of Object.entries(state.info.presets)) {
    if (!presetFits(key, state.vehicles[state.activeLeg])) continue;
    const b = document.createElement("button");
    b.textContent = p.label;
    b.classList.toggle("on", key === current);
    b.addEventListener("click", () => {
      state.legs[state.activeLeg] = presetValues(key);
      update();
    });
    chips.appendChild(b);
  }
  if (!current) {
    const b = document.createElement("button");
    b.textContent = "Custom";
    b.className = "on custom";
    chips.appendChild(b);
  }

  const box = $("sliders");
  box.innerHTML = "";
  const allowed = state.info.profiles[state.vehicles[state.activeLeg]].kinds;
  kindKeys().forEach((key, idx) => {
    if (!allowed.includes(key)) return;
    const k = KINDS[key];
    const v = active[idx];
    const row = document.createElement("div");
    row.className = "slider-row";
    row.innerHTML = `
      <div class="top"><i style="background:var(${k.color})"></i><span>${k.label}</span><em></em></div>
      <input type="range" min="0" max="100" step="1" aria-label="${k.label}">`;
    const input = row.querySelector("input");
    const word = row.querySelector("em");
    const show = (val) => {
      input.style.setProperty("--pct", `${val}%`);
      word.textContent = sliderWord(val);
      word.classList.toggle("never", val === 0);
    };
    input.value = v;
    input.style.setProperty("--c", `var(${k.color})`);
    show(v);
    input.addEventListener("input", () => show(+input.value));
    input.addEventListener("change", () => {
      state.legs[state.activeLeg][idx] = +input.value;
      update();
    });
    box.appendChild(row);
  });

  // High Elevation: same scale, but about how high up a road is rather than what it's made of.
  if (state.info.elevation?.ready) {
    const idx = kindKeys().length;
    const row = document.createElement("div");
    row.className = "slider-row elev";
    row.innerHTML = `
      <div class="top">${PEAK_ICON}<span>${esc(state.info.elevation.label)}</span><em></em></div>
      <input type="range" min="0" max="100" step="1" aria-label="${esc(state.info.elevation.label)}">
      <small>Ridges, passes and summit roads, over the valley floors.</small>`;
    const input = row.querySelector("input");
    const word = row.querySelector("em");
    const show = (val) => {
      input.style.setProperty("--pct", `${val}%`);
      word.textContent = val <= 25 ? "Stay low" : val <= 45 ? "Less" : val <= 55 ? "Neutral" : val <= 75 ? "More" : "Seek";
    };
    input.value = active[idx];
    input.style.setProperty("--c", "var(--k-elev)");
    show(active[idx]);
    input.addEventListener("input", () => show(+input.value));
    input.addEventListener("change", () => {
      state.legs[state.activeLeg][idx] = +input.value;
      update();
    });
    box.appendChild(row);
  }
}

$("apply-all").addEventListener("click", () => {
  const v = state.legs[state.activeLeg];
  state.legs = state.legs.map(() => [...v]);
  update();
});

const customizeOpen = () => $("customize").getAttribute("aria-expanded") === "true";
function setCustomize(open) {
  $("customize").setAttribute("aria-expanded", String(open));
  $("sliders").hidden = !open;
  store.set("customize", open ? "1" : "0");
}
$("customize").addEventListener("click", () => setCustomize(!customizeOpen()));
setCustomize(store.get("customize") === "1");

// ---------- search ----------
let searchCtl = null;

async function geocode(q, remote = true) {
  searchCtl?.abort();
  searchCtl = new AbortController();
  const c = map.getCenter();
  const res = await fetch(`/api/geocode?q=${encodeURIComponent(q)}&lat=${c.lat.toFixed(4)}&lon=${c.lng.toFixed(4)}&remote=${remote}`,
    { signal: searchCtl.signal });
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail || res.statusText);
  return body;
}

const splitTo = (q) => q.match(/^(.+?)\s+to\s+(.+)$/i);
const toStop = (h) => ({ lat: h.lat, lon: h.lon, label: h.name });

function showSuggestions(row, i, hits) {
  row.querySelector(".suggest")?.remove();
  if (!hits.length) return;
  const ul = document.createElement("ul");
  ul.className = "suggest";
  hits.forEach((h, j) => {
    const li = document.createElement("li");
    li.innerHTML = `<span class="pinico">●</span><span class="t"><b>${esc(h.name)}</b>${h.detail ? `<small>${esc(h.detail)}</small>` : ""}</span>`;
    if (j === 0) li.classList.add("active");
    li.addEventListener("mousedown", (ev) => ev.preventDefault());
    li.addEventListener("click", () => { ul.remove(); pick(i, h); });
    ul.appendChild(li);
  });
  row.appendChild(ul);
}

function attachSearch(input, row, i) {
  let timer = null, remoteTimer = null;
  const suggest = async (q, remote) => {
    try {
      const hits = await geocode(q, remote);
      if (input.value.trim() === q) showSuggestions(row, i, hits);
      return hits;
    } catch (err) {
      if (err.name !== "AbortError") console.warn(err);
      return null;
    }
  };
  input.addEventListener("input", () => {
    clearTimeout(timer);
    clearTimeout(remoteTimer);
    const q = input.value.trim();
    if (q.length < 2 || (i === 0 && splitTo(q))) { row.querySelector(".suggest")?.remove(); return; }
    // Offline places answer instantly; ask the online geocoder only once typing pauses.
    timer = setTimeout(async () => {
      const hits = await suggest(q, false);
      if (hits && hits.length < 3 && q.length >= 3) remoteTimer = setTimeout(() => suggest(q, true), 400);
    }, 60);
  });

  input.addEventListener("keydown", async (e) => {
    const list = row.querySelector(".suggest");
    if (list && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
      e.preventDefault();
      const items = [...list.children];
      let idx = items.findIndex((li) => li.classList.contains("active"));
      idx = (idx + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
      items.forEach((li, j) => li.classList.toggle("active", j === idx));
      return;
    }
    if (e.key === "Escape") { list?.remove(); return; }
    if (e.key !== "Enter") return;
    e.preventDefault();
    clearTimeout(timer);
    clearTimeout(remoteTimer);
    const q = input.value.trim();
    if (!q) return;

    const both = i === 0 && splitTo(q);
    if (both) {
      list?.remove();
      setStatus("Searching…");
      try {
        const a = await geocode(both[1]);
        const b = await geocode(both[2]);
        if (!a.length || !b.length) throw new Error(`Couldn't find “${!a.length ? both[1] : both[2]}”.`);
        setStatus("");
        state.stops = [toStop(a[0]), toStop(b[0])];
        state.legs = [state.legs[0]];
        state.vehicles = [state.vehicles[0]];
        update({ fit: true });
      } catch (err) {
        if (err.name !== "AbortError") setStatus(err.message, true);
      }
      return;
    }

    const active = list?.querySelector(".active");
    if (active) { active.click(); return; }
    try {
      const hits = await geocode(q);
      if (!hits.length) { setStatus("No results.", true); return; }
      pick(i, hits[0]);
    } catch (err) {
      if (err.name !== "AbortError") setStatus(`Search failed: ${err.message}`, true);
    }
  });
  input.addEventListener("blur", () => setTimeout(() => row.querySelector(".suggest")?.remove(), 150));
  input.addEventListener("focus", () => input.select());
}

function pick(i, hit) {
  setStatus("");
  state.stops[i] = toStop(hit);
  const next = state.stops.findIndex((s) => !s);
  update({ fit: next < 0 });
  if (next >= 0) {
    map.setView([hit.lat, hit.lon], Math.max(map.getZoom(), 11));
    $("stops").querySelectorAll("input")[next]?.focus();
  }
}

// ---------- stops ----------
function renderStops() {
  const box = $("stops");
  box.innerHTML = "";
  state.stops.forEach((s, i) => {
    const role = stopRole(i);
    const row = document.createElement("div");
    row.className = "stop";
    const ph = role === "start" ? "Start — or “Big Sur to Monterey”" : role === "end" ? "Destination" : "Stop";
    row.innerHTML = `
      <span class="dot ${role}">${role === "via" ? i : ""}</span>
      <input type="text" placeholder="${ph}" value="${s ? esc(s.label) : ""}" autocomplete="off" spellcheck="false" enterkeyhint="search">
      ${role === "via" ? `<button class="remove" aria-label="Remove stop">✕</button>` : ""}`;
    attachSearch(row.querySelector("input"), row, i);
    row.querySelector(".remove")?.addEventListener("click", () => removeStop(i));
    box.appendChild(row);
  });
}

$("add-via").addEventListener("click", () => {
  insertStop(state.stops.length - 1, null);
  state.activeLeg = state.legs.length - 1;
  update();
  $("stops").querySelectorAll("input")[state.stops.length - 2].focus();
});
$("swap").addEventListener("click", () => {
  state.stops.reverse();
  state.legs.reverse();
  state.vehicles.reverse();
  state.activeLeg = state.legs.length - 1 - state.activeLeg;
  update();
});
$("clear").addEventListener("click", () => {
  state.stops = [null, null];
  state.legs = [state.legs[state.activeLeg]];
  state.vehicles = [state.vehicles[state.activeLeg]];
  state.activeLeg = 0;
  state.route = null;
  setStatus("");
  update();
  $("stops").querySelector("input").focus();
});
$("grabber").addEventListener("click", () => $("panel").classList.toggle("collapsed"));

// ---------- location ----------
function locate(setAsStart) {
  if (!navigator.geolocation) { setStatus("Location isn't available in this browser.", true); return; }
  navigator.geolocation.getCurrentPosition(
    (p) => {
      const { latitude: lat, longitude: lon } = p.coords;
      meMarker?.remove();
      meMarker = L.marker([lat, lon], {
        interactive: false, icon: L.divIcon({ className: "", iconSize: [18, 18], iconAnchor: [9, 9], html: '<div class="me-dot"></div>' }),
      }).addTo(map);
      if (setAsStart && !state.stops[0]) {
        state.stops[0] = { lat, lon, label: "My Location" };
        update();
      }
      map.setView([lat, lon], Math.max(map.getZoom(), 12));
    },
    (err) => setStatus(`Couldn't get your location: ${err.message}`, true),
    { enableHighAccuracy: true, timeout: 10000 },
  );
}
$("locate-me").addEventListener("click", () => locate(true));

// ---------- vehicle ----------
const PEAK_ICON = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 5.5 10 11l2.9 3.9-1.7 1.3L7 10.5 1 19h22L14 5.5z" fill="currentColor"/></svg>`;
const icon = (d) => `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${d}" fill="currentColor"/></svg>`;
const PROFILE_ICONS = {
  car: icon("M18.92 6.01C18.72 5.42 18.16 5 17.5 5h-11c-.66 0-1.21.42-1.42 1.01L3 12v8c0 .55.45 1 1 1h1c.55 0 1-.45 1-1v-1h12v1c0 .55.45 1 1 1h1c.55 0 1-.45 1-1v-8l-2.08-5.99zM6.5 16c-.83 0-1.5-.67-1.5-1.5S5.67 13 6.5 13s1.5.67 1.5 1.5S7.33 16 6.5 16zm11 0c-.83 0-1.5-.67-1.5-1.5s.67-1.5 1.5-1.5 1.5.67 1.5 1.5-.67 1.5-1.5 1.5zM5 11l1.5-4.5h11L19 11H5z"),
  dualsport: icon("M19.44 9.03 15.41 5H11v2h3.59l2 2H5c-2.8 0-5 2.2-5 5s2.2 5 5 5c2.46 0 4.45-1.69 4.9-4h1.65l2.77-2.77c-.21.54-.32 1.14-.32 1.77 0 2.8 2.2 5 5 5s5-2.2 5-5c0-2.65-1.97-4.77-4.56-4.97zM7.82 15C7.4 16.15 6.28 17 5 17c-1.63 0-3-1.37-3-3s1.37-3 3-3c1.28 0 2.4.85 2.82 2H5v2h2.82zM19 17c-1.66 0-3-1.34-3-3s1.34-3 3-3 3 1.34 3 3-1.34 3-3 3z"),
};
function renderProfiles() {
  const box = $("profiles");
  box.innerHTML = "";
  for (const [key, p] of Object.entries(state.info.profiles)) {
    const b = document.createElement("button");
    b.innerHTML = `${PROFILE_ICONS[key] || ""}<span>${esc(p.label)}</span>`;
    b.setAttribute("role", "tab");
    b.classList.toggle("on", key === state.vehicles[state.activeLeg]);
    b.addEventListener("click", () => {
      if (state.vehicles[state.activeLeg] === key) return;
      state.vehicles[state.activeLeg] = key;
      // A bike-only style (e.g. Singletrack / OHV) makes no sense for the car; fall back to the default.
      const preset = presetOf(state.legs[state.activeLeg]);
      if (preset && !presetFits(preset, key)) state.legs[state.activeLeg] = defaultLeg();
      update();
    });
    box.appendChild(b);
  }
  // With several legs these tabs set the vehicle for the leg being edited.
  const note = $("mode-note");
  note.hidden = state.legs.length < 2;
  note.textContent = `Vehicle for ${stopLetter(state.activeLeg)} → ${stopLetter(state.activeLeg + 1)} · pick a leg under Route Style`;
}

// ---------- markers ----------
function pinIcon(i) {
  const role = stopRole(i);
  if (role === "start") return L.divIcon({ className: "", iconSize: [20, 20], iconAnchor: [10, 10], html: '<div class="pin-start"></div>' });
  if (role === "end") return L.divIcon({ className: "", iconSize: [30, 40], iconAnchor: [15, 40], html: '<div class="pin-end"><div class="head"></div><div class="stem"></div></div>' });
  return L.divIcon({ className: "", iconSize: [22, 22], iconAnchor: [11, 11], html: `<div class="pin-via">${i}</div>` });
}

function renderMarkers() {
  markerLayer.clearLayers();
  state.stops.forEach((s, i) => {
    if (!s) return;
    const m = L.marker([s.lat, s.lon], { draggable: true, icon: pinIcon(i), autoPan: true, zIndexOffset: 1000 }).addTo(markerLayer);
    m.on("dragend", () => {
      const ll = m.getLatLng();
      state.stops[i] = { lat: ll.lat, lon: ll.lng, label: fmtLL(ll.lat, ll.lng) };
      update();
    });
    if (stopRole(i) === "via") m.on("click", () => removeStop(i));
  });
}

map.on("click", async (e) => {
  if (await showMvumInfo(e.latlng)) return; // with MVUM on, a click on a forest road shows who may drive it
  const i = state.stops.findIndex((s) => !s);
  if (i < 0) return;
  state.stops[i] = { lat: e.latlng.lat, lon: e.latlng.lng, label: fmtLL(e.latlng.lat, e.latlng.lng) };
  update();
});

function insertVia(latlng, leg) {
  insertStop(leg + 1, { lat: latlng.lat, lon: latlng.lng, label: fmtLL(latlng.lat, latlng.lng) });
  update();
}

// ---------- gas stations ----------
const GAS_ICON = `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="m19.77 7.23.01-.01-3.72-3.72L15 4.56l2.11 2.11c-.94.36-1.61 1.26-1.61 2.33a2.5 2.5 0 0 0 2.5 2.5c.36 0 .69-.08 1-.21v7.21c0 .55-.45 1-1 1s-1-.45-1-1V14c0-1.1-.9-2-2-2h-1V5c0-1.1-.9-2-2-2H6c-1.1 0-2 .9-2 2v16h10v-7.5h1.5v5a2.5 2.5 0 0 0 5 0V9c0-.69-.28-1.32-.73-1.77zM12 10H6V5h6v5zm6 0c-.55 0-1-.45-1-1s.45-1 1-1 1 .45 1 1-.45 1-1 1z"/></svg>`;
const gasLayer = L.layerGroup().addTo(map);
const gasIcon = L.divIcon({ className: "", iconSize: [24, 24], iconAnchor: [12, 12], html: `<div class="gas-pin">${GAS_ICON}</div>` });
let gasOn = store.get("gas") !== "0";
let gasCtl = null;

function gasDetails(st) {
  const bits = [];
  if (st.brand) bits.push(esc(st.brand));
  if (st.hours) bits.push(st.hours === "24/7" ? "Open 24 hours" : esc(st.hours));
  if (st.diesel === 1) bits.push("Diesel");
  else if (st.diesel === 0) bits.push("No diesel");
  return bits.join(" · ");
}

// A map pin's popup: title, detail lines (HTML), and a button that routes through the place.
// Also the place's coordinates, to copy or open in Google Maps.
function placePopup(p, title, lines) {
  const div = document.createElement("div");
  div.className = "gas-popup";
  const ll = fmtLL(p.lat, p.lon);
  const gmaps = `https://www.google.com/maps/search/?api=1&query=${p.lat.toFixed(6)},${p.lon.toFixed(6)}`;
  div.innerHTML = `<b>${esc(title)}</b>${lines.filter(Boolean).map((l) => `<small>${l}</small>`).join("")}
    <div class="coords"><code>${ll}</code><button class="link-btn copy">Copy</button>
      <a href="${gmaps}" target="_blank" rel="noopener">Google Maps</a></div>
    <button class="text-btn add">Add as stop</button>`;
  div.querySelector(".add").addEventListener("click", () => {
    map.closePopup();
    addStopNearest({ lat: p.lat, lon: p.lon, label: title });
  });
  const copy = div.querySelector(".copy");
  copy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(ll);
      copy.textContent = "Copied";
    } catch { // no clipboard access: select the text so ⌘C works
      getSelection().selectAllChildren(div.querySelector("code"));
    }
  });
  return div;
}
const gasPopup = (st) => placePopup(st, st.name, [gasDetails(st)]);

// Fills the first empty stop, or slots the new stop in where it adds the least detour.
function addStopNearest(stop) {
  const empty = state.stops.findIndex((s) => !s);
  if (empty >= 0) {
    state.stops[empty] = stop;
    update();
    return;
  }
  const d = (a, b) => Math.hypot(a.lat - b.lat, (a.lon - b.lon) * Math.cos((a.lat * Math.PI) / 180));
  let best = 1, bestCost = Infinity;
  for (let i = 1; i < state.stops.length; i++) {
    const a = state.stops[i - 1], b = state.stops[i];
    const cost = d(a, stop) + d(stop, b) - d(a, b);
    if (cost < bestCost) { bestCost = cost; best = i; }
  }
  insertStop(best, stop);
  update();
}

async function loadGas() {
  gasCtl?.abort();
  if (!gasOn) { gasLayer.clearLayers(); return; }
  gasCtl = new AbortController();
  const b = map.getBounds().pad(0.2);
  try {
    const q = new URLSearchParams({ s: b.getSouth(), w: b.getWest(), n: b.getNorth(), e: b.getEast(), z: map.getZoom() });
    const stations = await (await fetch(`/api/fuel?${q}`, { signal: gasCtl.signal })).json();
    gasLayer.clearLayers();
    for (const st of stations) {
      withTooltip(L.marker([st.lat, st.lon], { icon: gasIcon }), () => gasTooltip(st))
        .bindPopup(() => gasPopup(st), PIN_POPUP).addTo(gasLayer);
    }
  } catch { /* aborted by a newer view, or offline */ }
}

function setGas(on) {
  gasOn = on;
  store.set("gas", on ? "1" : "0");
  loadGas();
}
map.on("moveend", loadGas);

// ---------- points of interest ----------
const iconEO = (d) => `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${d}" fill="currentColor" fill-rule="evenodd"/></svg>`;
const DROP = "M12 2.5c-5 4.4-7.5 8.1-7.5 11.3a7.5 7.5 0 0 0 15 0c0-3.2-2.5-6.9-7.5-11.3z";
const TENT = "M12 3 1.5 21h7.5L12 15.5 15 21h7.5L12 3z";
const BED = "M2 5h2.5v8h17.5v6h-2.5v-2.5h-15V19H2V5zm5.5 2.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5zm3.5.5h7.5a3.5 3.5 0 0 1 3.5 3.5V12H11V8z";
const POI_ICONS = {
  water: iconEO(DROP),
  spring: iconEO(`${DROP}M8 15.5c1.3 1 2.7 1 4 0s2.7-1 4 0v1.8c-1.3-1-2.7-1-4 0s-2.7 1-4 0z`),
  campground: iconEO(TENT),
  dispersed: iconEO(TENT),
  rv: iconEO("M2 6h14l5 5v6h-1.8a2.7 2.7 0 0 1-5.4 0H8.2a2.7 2.7 0 0 1-5.4 0H2V6zm2 2v4h4V8H4zm6 0v4h4V8h-4zm6 0v4h3.2L16 8.8V8z"),
  cabin: iconEO("M12 2.5 1.5 11.5h3V21h5.5v-6h4v6h5.5v-9.5h3L12 2.5z"),
  trailhead: iconEO("M11 2h2v3h6.5l2.5 2.5-2.5 2.5H13v12h-2V10H4.5L2 7.5 4.5 5H11V2z"),
  staging: PROFILE_ICONS.dualsport,
  hotel: iconEO(BED), motel: iconEO(BED), inn: iconEO(BED), hostel: iconEO(BED),
  rental: iconEO("M12 2.5 1.5 11.5h3V21h5.5v-6h4v6h5.5v-9.5h3L12 2.5z"),
  ghost_town: iconEO("M3 21V10h3V5h12v5h3v11h-7v-5h-4v5H3zM8 8v3h3V8H8zm5 0v3h3V8h-3z"),
  mine: iconEO("M2 21V11a10 10 0 0 1 20 0v10h-5v-9a5 5 0 0 0-10 0v9H2zm8.5 0v-6h3v6h-3z"),
  ruins: iconEO("M3 22v-2.5h18V22H3zm1.5-4V8l3 1.5V18h-3zm5.5 0V4h4v14h-4zm6 0v-6.5l3-2V18h-3z"),
  viewpoint: iconEO("M12 5C6.5 5 2.7 8.6 1 12c1.7 3.4 5.5 7 11 7s9.3-3.6 11-7c-1.7-3.4-5.5-7-11-7zm0 11.5a4.5 4.5 0 1 1 0-9 4.5 4.5 0 0 1 0 9zm0-2.2a2.3 2.3 0 1 0 0-4.6 2.3 2.3 0 0 0 0 4.6z"),
  peak: iconEO("M14 5.5 10 11l2.9 3.9-1.7 1.3L7 10.5 1 19h22L14 5.5z"),
  lookout: iconEO("M12 1.5 18.5 7H16v4h-1.2L17 22h-2.3l-.6-3.2H9.9L9.3 22H7l2.2-11H8V7H5.5L12 1.5zm-1.4 9.5-.4 5.5h3.6l-.4-5.5h-2.8z"),
  hot_spring: iconEO("M2 15.5c0-2.2 4.5-3.5 10-3.5s10 1.3 10 3.5v.5H2zM2 18h20a4 4 0 0 1-4 4H6a4 4 0 0 1-4-4zM7.2 2.5l1.6.8c-1 1.8 1 3-.1 5.5l-1.6-.8c.9-2-1-3.2.1-5.5zm4 0 1.6.8c-1 1.8 1 3-.1 5.5l-1.6-.8c.9-2-1-3.2.1-5.5zm4 0 1.6.8c-1 1.8 1 3-.1 5.5l-1.6-.8c.9-2-1-3.2.1-5.5z"),
  arch: iconEO("M1.5 21V10.5C1.5 6 6.2 3 12 3s10.5 3 10.5 7.5V21h-5.5v-8c0-2.4-2.2-4-5-4s-5 1.6-5 4v8H1.5z"),
  cave: iconEO("M1 21 7.5 7l2.7 3L13.5 4 23 21H1zm8 0h6v-3.5a3 3 0 0 0-6 0V21z"),
  petroglyph: iconEO("M12 2a2.2 2.2 0 1 1 0 4.4A2.2 2.2 0 0 1 12 2zm-1.2 5.5h2.4v3.6l4.2-3 1.3 1.7-5.5 4v2.6l3.4 5.6h-2.6L12 17.6 10 22H7.4l3.4-5.6v-2.6L5.3 9.8l1.3-1.7 4.2 3V7.5z"),
};
const POI_LABELS = {
  water: "Drinking water", spring: "Spring", campground: "Campground", dispersed: "Dispersed camping",
  rv: "RV park", cabin: "Backcountry cabin", trailhead: "Trailhead", staging: "OHV staging area",
  hotel: "Hotel", motel: "Motel", inn: "Guest house / B&B", hostel: "Hostel", rental: "Cabin or vacation rental",
  ghost_town: "Ghost town", mine: "Mine", ruins: "Ruins", viewpoint: "Viewpoint", peak: "Peak",
  lookout: "Fire lookout", hot_spring: "Hot spring", arch: "Arch", cave: "Cave", petroglyph: "Petroglyphs",
};
// The marker panel on the right: one row per pin type, grouped. Click a row to show or hide that
// type, a group heading for the whole group. Sights get small pins: there are thousands of peaks.
const MARKER_GROUPS = [
  { key: "gas", label: "Gas", kinds: ["gas"] },
  { key: "water", label: "Water", kinds: ["water", "spring"] },
  { key: "camp", label: "Camping", kinds: ["campground", "dispersed", "rv", "cabin"] },
  { key: "trail", label: "Trailheads", kinds: ["trailhead", "staging"] },
  { key: "lodging", label: "Lodging", kinds: ["motel", "hotel", "inn", "hostel", "rental"] },
  { key: "sight", label: "Sights", small: true,
    kinds: ["ghost_town", "mine", "ruins", "petroglyph", "hot_spring", "peak", "viewpoint", "lookout", "arch", "cave"] },
];
const groupOf = Object.fromEntries(MARKER_GROUPS.flatMap((g) => g.kinds.map((k) => [k, g])));
const poiOff = new Set((() => { try { return JSON.parse(store.get("poi-off") || "[]"); } catch { return []; } })());
const isOn = (kind) => (kind === "gas" ? gasOn : !poiOff.has(kind));
const poiLayer = L.layerGroup().addTo(map);
const poiIcons = {};
let poiCtl = null;

function setKinds(kinds, on) {
  for (const k of kinds) {
    if (k === "gas") { if (gasOn !== on) setGas(on); }
    else if (on) poiOff.delete(k);
    else poiOff.add(k);
  }
  store.set("poi-off", JSON.stringify([...poiOff]));
  loadPois();
  renderMarkerPanel();
}

function poiIcon(kind, small) {
  return (poiIcons[kind] ||= L.divIcon({
    className: "", iconSize: small ? [20, 20] : [24, 24], iconAnchor: small ? [10, 10] : [12, 12],
    html: `<div class="poi-pin k-${kind}${small ? " small" : ""}">${POI_ICONS[kind] || ""}</div>`,
  }));
}

// Shown on hover when a place has no description of its own in OSM.
const POI_ABOUT = {
  water: "Drinking water tap or fill station.",
  spring: "Natural spring. Flow varies by season; treat the water unless it's marked potable.",
  campground: "Developed campground with marked sites, usually with toilets and often a fee.",
  dispersed: "Dispersed camping: free, no facilities, on public land outside developed campgrounds.",
  rv: "RV park or caravan site.",
  cabin: "Backcountry cabin or hut, usually first come, first served.",
  trailhead: "Trailhead: parking and access point for trails.",
  staging: "OHV staging area: room to park the truck and unload bikes or ATVs for the trails.",
  inn: "Guest house, B&B or inn.",
  hostel: "Hostel: shared rooms or dorm beds.",
  rental: "Cabin, chalet or vacation rental, usually booked ahead.",
  ghost_town: "Abandoned town. Often on or near private claims, so look but don't take.",
  mine: "Old mine shaft, adit or workings. Never go inside; shafts can be hidden and unstable.",
  ruins: "Remains of a building or structure.",
  petroglyph: "Rock art. Look without touching; it's protected by law.",
  hot_spring: "Natural hot spring. Temperatures vary; test before getting in.",
  peak: "Mountain summit.",
  viewpoint: "Viewpoint or overlook.",
  lookout: "Fire lookout tower. Some are staffed in summer, and a few can be rented.",
  arch: "Natural rock arch.",
  cave: "Cave entrance. Many close seasonally to protect bats.",
};
// "Ruins · stamp mill", "Mine · gold"
const poiKindLabel = (p) => [POI_LABELS[p.kind] || "", p.what ? esc(p.what) : ""].filter(Boolean).join(" · ");

function poiFacts(p) {
  const yesNo = (v, yes, no) => (v === true ? yes : v === false ? no : "");
  return [
    p.ele != null ? `${Math.round(p.ele * 3.28084).toLocaleString()} ft` : "",
    yesNo(p.fee, "Fee", "Free"),
    yesNo(p.toilets, "Toilets", "No toilets"),
    p.kind === "spring" ? yesNo(p.water, "Potable", "Not potable") || "Unverified, treat before drinking"
      : yesNo(p.water, "Water", "No water"),
    p.seasonal != null ? (p.seasonal ? `Seasonal (${esc(p.seasonal)})` : "Seasonal") : "",
    p.reservation === "required" ? "Reservation required" : "",
    p.stars ? "★".repeat(p.stars) : "",
    p.phone ? esc(p.phone) : "",
  ].filter(Boolean).join(" · ");
}

function poiPopup(p) {
  return placePopup(p, p.name || POI_LABELS[p.kind] || "", [
    p.name || p.what ? `<span class="poi-kind k-${p.kind}">${poiKindLabel(p)}</span>` : "",
    p.private ? `<span class="poi-private">Private, no public access</span>` : "",
    poiFacts(p),
    p.desc ? `<span class="poi-desc">${esc(p.desc)}</span>` : "",
    p.operator ? esc(p.operator) : "",
    p.hours ? esc(p.hours) : "",
    /^https?:\/\//.test(p.url || "") ? `<a href="${esc(p.url)}" target="_blank" rel="noopener">Website</a>` : "",
  ]);
}

// Hover card: what the place is, without having to click.
function poiTooltip(p) {
  return `<div class="pin-tip">
    <b>${esc(p.name || POI_LABELS[p.kind] || "")}</b>
    <span class="poi-kind k-${p.kind}">${poiKindLabel(p)}</span>
    ${p.private ? `<span class="poi-private">Private, no public access</span>` : ""}
    ${poiFacts(p) ? `<small>${poiFacts(p)}</small>` : ""}
    <p>${esc(p.desc || POI_ABOUT[p.kind] || "")}</p>
    <small class="ll">${fmtLL(p.lat, p.lon)} · Click for details</small>
  </div>`;
}
const gasTooltip = (st) => `<div class="pin-tip"><b>${esc(st.name)}</b><span class="poi-kind k-gas">Gas station</span>
  ${gasDetails(st) ? `<small>${gasDetails(st)}</small>` : ""}<small class="ll">${fmtLL(st.lat, st.lon)} · Click for details</small></div>`;

// Pin popups close with their ×, Esc, a click on the map, or a second click on the pin.
const PIN_POPUP = { closeButton: true, autoPanPadding: [60, 60] };
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !e.target.closest("input, textarea")) map.closePopup();
});

// Hover cards only where there's a mouse; on touch screens a tap opens the popup instead.
const canHover = matchMedia("(hover: hover)").matches;
function withTooltip(marker, content) {
  if (!canHover) return marker;
  marker.bindTooltip(() => content(), { direction: "top", offset: [0, -12], className: "pin-tooltip", opacity: 1 });
  // While its popup is open, the hover card would only cover it.
  marker.on("popupopen", () => marker.closeTooltip());
  marker.on("tooltipopen", () => { if (marker.isPopupOpen()) marker.closeTooltip(); });
  return marker;
}

async function loadPois() {
  poiCtl?.abort();
  const z = map.getZoom();
  const kinds = MARKER_GROUPS.filter((g) => g.key !== "gas").flatMap((g) => g.kinds).filter(isOn);
  if (!kinds.length) { poiLayer.clearLayers(); return; }
  poiCtl = new AbortController();
  const b = map.getBounds().pad(0.2);
  try {
    const q = new URLSearchParams({ s: b.getSouth(), w: b.getWest(), n: b.getNorth(), e: b.getEast(), kinds: kinds.join(","), z });
    const points = await (await fetch(`/api/pois?${q}`, { signal: poiCtl.signal })).json();
    poiLayer.clearLayers();
    // Server order is most important first; add in reverse so those pins end up on top.
    for (const p of points.reverse()) {
      withTooltip(L.marker([p.lat, p.lon], { icon: poiIcon(p.kind, groupOf[p.kind]?.small), zIndexOffset: -1000 }), () => poiTooltip(p))
        .bindPopup(() => poiPopup(p), PIN_POPUP).addTo(poiLayer);
    }
  } catch { /* aborted by a newer view, or offline */ }
}
map.on("moveend", loadPois);

// ---------- overlays: land agencies' own map services ----------
// An ArcGIS MapServer drawn on request: each image twice the tile's size, crisp on retina screens.
// The server draws at its 96 dpi unless told otherwise, so at double size its labels come out half
// as big; the `dpi` option scales lines and labels back up.
const ArcGISLayer = L.TileLayer.extend({
  getTileUrl(c) {
    const ts = this.getTileSize().x, px = ts * 2;
    const half = 20037508.342789244, size = (2 * half * ts) / (256 * 2 ** c.z);
    const x0 = -half + c.x * size, y1 = half - c.y * size;
    const q = new URLSearchParams({ bbox: [x0, y1 - size, x0 + size, y1].join(","), bboxSR: 3857, imageSR: 3857,
      size: `${px},${px}`, format: "png32", transparent: true, layers: this.options.layers, f: "image" });
    if (this.options.dpi) q.set("dpi", this.options.dpi);
    return `${this._url}/export?${q}`;
  },
});
const FS_EDW = "https://apps.fs.usda.gov/arcx/rest/services/EDW";
const BLM_SMA = "https://gis.blm.gov/arcgis/rest/services/lands/BLM_Natl_SMA_Cached_without_PriUnk/MapServer";
// The BLM's own colours for who manages the land; private land is left clear.
const LAND_KEY = [["BLM", "#fee679"], ["Forest Service", "#ccebc5"], ["National Park", "#cabddc"], ["State", "#b3e3ee"],
  ["Fish & Wildlife", "#7fcca7"], ["Military", "#fbb4ce"], ["Tribal", "#fdb46c"], ["Reclamation", "#ffffb3"],
  ["Other federal", "#e4c49f"], ["Local", "#8fb5be"]];
const OVERLAYS = [
  { key: "land", label: "Public land", swatch: "land",
    note: "Who manages the land. BLM land is usually open to dispersed camping; private land is left clear.",
    make: () => L.tileLayer(`${BLM_SMA}/tile/{z}/{y}/{x}`, { pane: "land", opacity: 0.55, maxNativeZoom: 14, maxZoom: 19, attribution: "Land status: BLM" }) },
  { key: "wilderness", label: "Wilderness areas", swatch: "wilderness",
    note: "No motor vehicles or bikes inside wilderness boundaries.",
    make: () => new ArcGISLayer(`${FS_EDW}/EDW_Wilderness_01/MapServer`, { layers: "show:0", pane: "land", opacity: 0.6, maxZoom: 19, attribution: "Wilderness: USDA Forest Service" }) },
  { key: "forests", label: "Forest boundaries", swatch: "forests",
    make: () => new ArcGISLayer(`${FS_EDW}/EDW_ForestSystemBoundaries_01/MapServer`, { layers: "show:0,1", pane: "lines", maxZoom: 19, attribution: "Forest boundaries: USDA Forest Service" }) },
  { key: "mvum", label: "MVUM roads & trails", swatch: "mvum", minZoom: 10,
    note: "Forest Service motor vehicle use maps, from zoom 10. The numbers are Forest Service road and trail numbers; click one for the vehicles allowed and dates open. Not every forest publishes this data.",
    // Big tiles: labels are cut at tile edges, so fewer edges means fewer cut-off road numbers.
    make: () => new ArcGISLayer(`${FS_EDW}/EDW_MVUM_01/MapServer`, { layers: "show:1,2", pane: "lines", tileSize: 512, dpi: 240, minZoom: 10, maxZoom: 19, attribution: "MVUM: USDA Forest Service" }) },
  { key: "camping", label: "Dispersed camping", swatch: "camping", minZoom: 9,
    note: "Read from each forest's printed motor vehicle use maps, from zoom 9. Click a line or area for the rules and the source map. Works offline.",
    make: () => new CampingLayer() },
];
map.createPane("land").style.zIndex = 210;  // fills: over the basemap, under our road overlay and the route
map.createPane("lines").style.zIndex = 260; // boundaries and MVUM lines: over our road overlay
const overlaysOn = new Set((() => { try { return JSON.parse(store.get("overlays") || "[]"); } catch { return []; } })());
const overlayLayers = {};

function setOverlay(key, on) {
  if (on) overlaysOn.add(key);
  else overlaysOn.delete(key);
  store.set("overlays", JSON.stringify([...overlaysOn]));
  syncOverlays();
  renderMarkerPanel();
}
function syncOverlays() {
  for (const o of OVERLAYS) {
    const on = overlaysOn.has(o.key);
    if (on && !overlayLayers[o.key]) overlayLayers[o.key] = o.make().addTo(map);
    if (!on && overlayLayers[o.key]) { overlayLayers[o.key].remove(); delete overlayLayers[o.key]; }
  }
}

// ---------- dispersed camping: rules read from the forests' MVUM PDFs (gravelmaps/camping.py) ----------
const CAMP = { yes: "#f2c200", no: "#d93025", casing: "#3d3200" };
const campRenderer = L.canvas({ pane: "lines", tolerance: 6 });
const sideWord = { left: "left side", right: "right side", both: "both sides" };
const campHow = {
  table: "Listed in the map's Dispersed Camping table.",
  dots: "Marked with camping dots beside the road on the map.",
  rule: "Forest-wide rule on the map.",
};

// One map's camping rules as popup lines. `full` adds the forest-wide statements word for word.
function sheetLines(sh, full = true) {
  const src = `<a href="${esc(sh.url)}" target="_blank" rel="noopener">${esc(sh.title)}${sh.year ? ` (${sh.year})` : ""}</a>`;
  const lines = [`<b class="sub">Source:</b> ${esc(sh.forest)}, ${src}`];
  if (sh.prohibited) lines.push(`<b class="sub">Not allowed:</b> ${esc(sh.prohibited)}`);
  if (full) for (const r of sh.rules || []) lines.push(`<b class="sub">Rule:</b> ${esc(r.text)}`);
  if (sh.tables?.length) lines.push(`This map lists ${sh.tables.reduce((n, t) => n + t.ids, 0)} roads with camping corridors (${sh.tables[0].text}).`);
  if (sh.roadside) lines.push(sh.roadside);
  if (!sh.has_text) lines.push("This map is a scanned image, so its notes couldn't be read; check the PDF.");
  for (const n of sh.notes || []) lines.push(`<b class="sub">Note:</b> ${esc(n)}`);
  return lines;
}

async function campingAt(lat, lon) {
  try { return await (await fetch(`/api/camping/at?lat=${lat}&lon=${lon}`)).json(); } catch { return null; }
}

const CampingLayer = L.LayerGroup.extend({
  onAdd(m) {
    L.LayerGroup.prototype.onAdd.call(this, m);
    this._load = () => this.load();
    m.on("moveend", this._load);
    this.load();
  },
  onRemove(m) {
    m.off("moveend", this._load);
    this.ctl?.abort();
    L.LayerGroup.prototype.onRemove.call(this, m);
  },
  async load() {
    this.ctl?.abort();
    if (map.getZoom() < 9) { this.clearLayers(); return; }
    this.ctl = new AbortController();
    const b = map.getBounds().pad(0.2);
    let d;
    try {
      d = await (await fetch(`/api/camping?s=${b.getSouth()}&w=${b.getWest()}&n=${b.getNorth()}&e=${b.getEast()}`, { signal: this.ctl.signal })).json();
    } catch { return; }
    this.clearLayers();
    for (const z of d.zones) {
      const poly = L.polygon(z.rings.map((r) => r.map(([x, y]) => [y, x])), {
        renderer: campRenderer, color: CAMP.no, weight: 1, dashArray: "4 4", fillColor: CAMP.no, fillOpacity: 0.12 });
      poly.on("click", (e) => {
        L.DomEvent.stopPropagation(e);
        const lines = [esc(z.note), `<b class="sub">Source:</b> ${esc(z.src)}${z.url ? `, <a href="${esc(z.url)}" target="_blank" rel="noopener">more</a>` : ""}`];
        L.popup(PIN_POPUP).setLatLng(e.latlng).setContent(placePopup({ lat: e.latlng.lat, lon: e.latlng.lng }, `No dispersed camping: ${z.name}`, lines)).openOn(map);
      });
      this.addLayer(poly);
    }
    for (const r of d.roads) {
      const ll = r.c.map((ln) => ln.map(([x, y]) => [y, x]));
      const color = r.s === "yes" ? CAMP.yes : CAMP.no;
      this.addLayer(L.polyline(ll, { renderer: campRenderer, interactive: false, color: CAMP.casing, weight: 7, opacity: 0.55 }));
      const line = L.polyline(ll, { renderer: campRenderer, color, weight: 4, opacity: 1, dashArray: r.t === "trail" ? "6 5" : null });
      line.on("click", (e) => { L.DomEvent.stopPropagation(e); this.roadPopup(r, e.latlng); });
      this.addLayer(line);
    }
    for (const s of d.sites) {
      const mk = L.circleMarker([s.lat, s.lon], { renderer: campRenderer, radius: 7, color: CAMP.casing, weight: 2, fillColor: CAMP.yes, fillOpacity: 1 });
      mk.on("click", (e) => {
        L.DomEvent.stopPropagation(e);
        const lines = ["Dispersed camping area listed by the Forest Service.", esc(s.fees),
          s.url ? `<a href="${esc(s.url)}" target="_blank" rel="noopener">Forest Service page</a>` : "", esc(s.forest)];
        L.popup(PIN_POPUP).setLatLng([s.lat, s.lon]).setContent(placePopup(s, s.name, lines)).openOn(map);
      });
      this.addLayer(mk);
    }
  },
  async roadPopup(r, latlng) {
    const title = r.name ? `${r.name.toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase())} (${r.t === "trail" ? "Trail" : "Road"} ${r.id})` : `${r.t === "trail" ? "Trail" : "Road"} ${r.id}`;
    const head = r.s === "yes"
      ? `<b class="sub">Dispersed camping allowed:</b> drive off the ${r.t} to camp${r.ft ? ` up to ${r.ft} ft from its centerline` : " (the distance is in its map's camping table)"}${r.side ? `, ${sideWord[r.side]}` : ""}.`
      : `<b class="sub">No driving off the ${r.t} to camp</b> on this forest.`;
    const lines = [head, campHow[r.how] || ""];
    const popup = L.popup(PIN_POPUP).setLatLng(latlng).setContent(placePopup({ lat: latlng.lat, lon: latlng.lng }, title, lines)).openOn(map);
    const at = await campingAt(latlng.lat, latlng.lng);
    const sh = at?.sheets.find((s) => s.i === r.src) || at?.sheets[0];
    if (sh && popup.isOpen()) popup.setContent(placePopup({ lat: latlng.lat, lon: latlng.lng }, title, [...lines, ...sheetLines(sh, r.how === "rule")]));
  },
});

// MVUM key: the Forest Service's own symbols (from its legend), with what each one allows.
// [layer, symbol value, name, meaning]; seasonal versions are the same symbol on a grey band.
const MVUM_KEY = [
  ["Roads"],
  [1, "1", "All vehicles", "Cars, trucks, OHVs, ATVs and motorcycles, street-legal or not."],
  [1, "3", "Highway-legal only", "Licensed, street-legal vehicles only. No unregistered OHVs or dirt bikes."],
  [1, "11", "Special designation", "Its own rules; click the road for details."],
  ["Trails"],
  [2, "5", "All vehicles", "Open to anything, full-size 4x4s included."],
  [2, "7", "50\" wide or less", "ATVs, small side-by-sides and motorcycles."],
  [2, "16", "Wheeled, 50\" or less", "As above, but no tracked vehicles."],
  [2, "9", "Motorcycles only", "Single-track for dirt bikes."],
  [2, "11", "Special designation", "Its own rules; click the trail for details."],
];
let mvumSymbols = null, mvumSymbolsLoading = false;
async function loadMvumSymbols() {
  if (mvumSymbols || mvumSymbolsLoading) return;
  mvumSymbolsLoading = true;
  try {
    const d = await (await fetch(`${FS_EDW}/EDW_MVUM_01/MapServer/legend?f=json&size=36,18&dpi=192`)).json();
    mvumSymbols = {};
    for (const l of d.layers) for (const x of l.legend) mvumSymbols[`${l.layerId}:${x.values?.[0]}`] = `data:${x.contentType};base64,${x.imageData}`;
    renderMarkerPanel();
  } catch { /* offline: the key shows names only */ } finally { mvumSymbolsLoading = false; }
}
function campKeyHtml() {
  if (state.info && !state.info.camping?.ready) {
    return `<p class="ov-note"><b>Not built yet.</b> Run <code>python -m gravelmaps camping</code> once, then restart.</p>`;
  }
  const row = (sym, name, desc) => `<div class="mk-row"><span class="mk-sym camp">${sym}</span><div><b>${name}</b><small>${desc}</small></div></div>`;
  const line = (c, dash) => `<svg viewBox="0 0 36 18"><line x1="2" y1="9" x2="34" y2="9" stroke="${CAMP.casing}" stroke-width="6" stroke-opacity=".55"/><line x1="2" y1="9" x2="34" y2="9" stroke="${c}" stroke-width="4" ${dash ? 'stroke-dasharray="6 5"' : ""}/></svg>`;
  return `<div class="mvum-key">
    ${row(line(CAMP.yes), "Drive off to camp", "Up to the distance its map allows; click for the rule.")}
    ${row(line(CAMP.yes, true), "Same, on a trail", "")}
    ${row(line(CAMP.no), "No driving off to camp", "The whole forest prohibits it.")}
    ${row(`<svg viewBox="0 0 36 18"><rect x="3" y="2" width="30" height="14" fill="${CAMP.no}" fill-opacity=".18" stroke="${CAMP.no}" stroke-dasharray="3 3"/></svg>`, "No dispersed camping", "Private, LADWP, parks and closures (Eastern Sierra).")}
    ${row(`<svg viewBox="0 0 36 18"><circle cx="18" cy="9" r="6" fill="${CAMP.yes}" stroke="${CAMP.casing}" stroke-width="2"/></svg>`, "Camping area", "Listed by the Forest Service.")}
    <p class="ov-note camp-note">Other forest roads: their map has no corridors, so park within one vehicle length of the road and walk in. Turn on MVUM and click a road for its forest's rule.${state.info?.camping?.built ? ` Maps read ${state.info.camping.built}.` : ""}</p></div>`;
}

function mvumKeyHtml() {
  loadMvumSymbols();
  const sym = (l, v) => `<span class="mk-sym">${mvumSymbols?.[`${l}:${v}`] ? `<img src="${mvumSymbols[`${l}:${v}`]}" alt="">` : ""}</span>`;
  return `<div class="mvum-key">${MVUM_KEY.map(([l, v, name, desc]) => v === undefined
    ? `<div class="mk-head">${l}</div>`
    : `<div class="mk-row">${sym(l, v)}<div><b>${name}</b><small>${desc}</small></div></div>`).join("")}
    <div class="mk-row">${sym(1, "2")}<div><b>Grey band: seasonal</b><small>Open only on the dates in its popup.</small></div></div></div>`;
}

// MVUM details for a clicked road or trail: the vehicle classes it's open to, and when.
const MVUM_VEHICLES = [["passengervehicle", "passengervehicle_datesopen", "Cars"],
  ["highclearancevehicle", "highclearancevehicle_datesopen", "High-clearance vehicles"],
  ["other_ohv_gt50inches", "other_ohv_gt50_datesopen", "UTVs / OHVs over 50\""],
  ["atv", "atv_datesopen", "ATVs"], ["motorcycle", "motorcycle_datesopen", "Motorcycles"]];
const afterDash = (v) => (v || "").replace(/^[^-]*-\s*/, "").toLowerCase();

async function showMvumInfo(latlng) {
  if (!overlaysOn.has("mvum") || map.getZoom() < 10) return false;
  const p = map.latLngToContainerPoint(latlng);
  const a = map.containerPointToLatLng(p.subtract([8, 8])), b = map.containerPointToLatLng(p.add([8, 8]));
  const q = new URLSearchParams({ geometry: [a.lng, b.lat, b.lng, a.lat].join(","), geometryType: "esriGeometryEnvelope",
    inSR: 4326, spatialRel: "esriSpatialRelIntersects", outFields: "*", returnGeometry: false, resultRecordCount: 1, f: "json" });
  let hit = null, layer = 0;
  try {
    const res = await Promise.all([1, 2].map((l) => fetch(`${FS_EDW}/EDW_MVUM_01/MapServer/${l}/query?${q}`).then((r) => r.json())));
    layer = res.findIndex((r) => r.features?.length);
    hit = layer >= 0 ? res[layer].features[0].attributes : null;
  } catch { return false; }
  if (!hit) return false;
  const kind = layer === 0 ? "Road" : "Trail";
  const title = hit.name ? hit.name.toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase()) : `${kind} ${hit.id}`;
  const open = MVUM_VEHICLES.filter(([k]) => hit[k] === "open").map(([k, d, label]) =>
    hit[d] && hit[d] !== "01/01-12/31" ? `${label} (${esc(hit[d])})` : label);
  const lines = [
    `<span class="poi-kind mvum-kind">${kind} ${esc(hit.id || "")}</span>`,
    esc(hit.mvum_symbol_name || ""),
    open.length ? `<b class="sub">Open to:</b> ${open.join(", ")}` : "Closed to motor vehicles",
    [hit.operationalmaintlevel && `Maintained for ${afterDash(hit.operationalmaintlevel)}`,
     hit.surfacetype && `${afterDash(hit.surfacetype)} surface`].filter(Boolean).map(esc).join(" · "),
    esc([hit.forestname, hit.districtname].filter(Boolean).join(" · ")),
  ];
  const popup = L.popup(PIN_POPUP).setLatLng(latlng).setContent(placePopup({ lat: latlng.lat, lon: latlng.lng }, title, lines)).openOn(map);
  // What this forest's printed map says about camping along its roads.
  const sh = (await campingAt(latlng.lat, latlng.lng))?.sheets[0];
  if (sh && popup.isOpen()) {
    const ft = sh.rules.find((r) => r.applies !== (layer === 0 ? "trails" : "roads"));
    const camp = sh.prohibited ? "no driving off roads to camp on this forest."
      : ft ? `drive up to ${ft.ft} ft off the ${kind.toLowerCase()} to camp (forest-wide rule).`
      : sh.tables.length || sh.dots ? "only along roads its map marks; turn on Dispersed camping to see them."
      : "no corridors on its map, so park within one vehicle length and walk in.";
    popup.setContent(placePopup({ lat: latlng.lat, lon: latlng.lng }, title,
      [...lines, `<b class="sub">Camping:</b> ${camp} <a href="${esc(sh.url)}" target="_blank" rel="noopener">MVUM PDF</a>`]));
  }
  return true;
}

function renderMarkerPanel() {
  const box = $("markers");
  // Each card is open by default, except on phones where it would cover the map.
  const isOpen = (key) => (store.get(key) ?? (innerWidth > 640 ? "1" : "0")) === "1";
  const markersOpen = isOpen("markers-open"), overlaysOpen = isOpen("overlays-open");
  const icon = (k) => (k === "gas" ? GAS_ICON : POI_ICONS[k]);
  const label = (k) => (k === "gas" ? "Gas station" : POI_LABELS[k]);
  const head = (key, title, open, extra = "") => `<div class="panel-head">
      <button class="head-toggle" data-toggle="${key}" aria-expanded="${open}">${title}<span>${open ? "▾" : "▸"}</span></button>${extra}</div>`;
  // The switch checks or unchecks every type: turn all off, then pick just the ones you want.
  const anyOn = MARKER_GROUPS.some((g) => g.kinds.some(isOn));
  const z = map.getZoom();
  box.innerHTML = `<div class="card poi-card${markersOpen ? "" : " closed"}">
      ${head("markers-open", "Map Markers", markersOpen,
        `<button class="switch${anyOn ? " on" : ""}" role="switch" aria-checked="${anyOn}" title="${anyOn ? "Uncheck" : "Check"} all markers"><i></i></button>`)}
      <div class="panel-body">${MARKER_GROUPS.map((g) => `
        <button class="group${g.kinds.some(isOn) ? "" : " off"}" data-group="${g.key}" title="Show or hide all ${g.label.toLowerCase()}">${g.label}</button>
        ${g.kinds.map((k) => `<button class="item${isOn(k) ? "" : " off"}" data-kind="${k}" aria-pressed="${isOn(k)}">
          <span class="poi-pin small k-${k}">${icon(k)}</span>${label(k)}</button>`).join("")}`).join("")}</div>
    </div>
    <div class="card ov-card${overlaysOpen ? "" : " closed"}">
      ${head("overlays-open", "Map Overlays", overlaysOpen)}
      <div class="panel-body">${OVERLAYS.map((o) => `<button class="item${overlaysOn.has(o.key) ? "" : " off"}" data-overlay="${o.key}" aria-pressed="${overlaysOn.has(o.key)}">
        <span class="ov-swatch ov-${o.swatch}"></span>${o.label}</button>
        ${overlaysOn.has(o.key) && o.note ? `<p class="ov-note">${o.note}${o.minZoom && z < o.minZoom ? " <b>Zoom in to see it.</b>" : ""}</p>` : ""}
        ${overlaysOn.has(o.key) && o.key === "mvum" ? mvumKeyHtml() : ""}
        ${overlaysOn.has(o.key) && o.key === "camping" ? campKeyHtml() : ""}
        ${overlaysOn.has(o.key) && o.key === "land" ? `<div class="land-key">${LAND_KEY.map(([l, c]) => `<span><i style="background:${c}"></i>${l}</span>`).join("")}</div>` : ""}`).join("")}</div>
    </div>`;
  box.querySelector(".switch").addEventListener("click", () => setKinds(MARKER_GROUPS.flatMap((g) => g.kinds), !anyOn));
  box.querySelectorAll("[data-toggle]").forEach((b) => b.addEventListener("click", () => {
    store.set(b.dataset.toggle, isOpen(b.dataset.toggle) ? "0" : "1");
    renderMarkerPanel();
  }));
  box.querySelectorAll("[data-overlay]").forEach((b) => b.addEventListener("click", () => setOverlay(b.dataset.overlay, !overlaysOn.has(b.dataset.overlay))));
  box.querySelectorAll("[data-kind]").forEach((b) => b.addEventListener("click", () => setKinds([b.dataset.kind], !isOn(b.dataset.kind))));
  box.querySelectorAll("[data-group]").forEach((b) => b.addEventListener("click", () => {
    const g = MARKER_GROUPS.find((x) => x.key === b.dataset.group);
    setKinds(g.kinds, !g.kinds.some(isOn)); // any on: hide the group; all off: show it
  }));
}

setGas(gasOn);
loadPois();
syncOverlays();
renderMarkerPanel();
map.on("zoomend", () => { if (OVERLAYS.some((o) => o.minZoom && overlaysOn.has(o.key))) renderMarkerPanel(); }); // overlays' "zoom in" notes
$("legend").innerHTML = Object.values(KINDS)
  .map((k) => `<div><i style="background:var(${k.color})"></i>${k.label}</div>`).join("");

// Fuel range: miles on a tank, 0 = off. Fill-ups are planned from the stations along the route.
let fuelRange = Math.min(1000, Math.max(0, +store.get("fuel-range") || 0));
function showFuelRange() {
  const input = $("fuel-range");
  input.value = fuelRange;
  input.style.setProperty("--pct", `${fuelRange / 10}%`);
  $("fuel-range-val").textContent = fuelRange ? `${fuelRange} mi` : "Off";
}
$("fuel-range").addEventListener("input", (e) => {
  fuelRange = +e.target.value;
  showFuelRange();
  if (state.route) renderGas(state.route);
});
$("fuel-range").addEventListener("change", () => store.set("fuel-range", String(fuelRange)));
showFuelRange();

/** Starting on a full tank, drive to the farthest station still in range and fill up there. Where
 * the next station (or the end) is out of reach, flag the stretch and carry on from that station.
 * A station under SAME_TOWN_M ahead is no progress (topping off in town), and none at the end counts. */
const SAME_TOWN_M = 3200;
function planFuel(stations, total, range) {
  const fills = new Set(), short = [];
  let pos = 0, i = 0;
  while (total - pos > range + 1) { // +1 m: float slack when the end is exactly a tank away
    while (i < stations.length && stations[i].at_m <= pos + range + 1) i++;
    if (i > 0 && stations[i - 1].at_m > pos + SAME_TOWN_M) {
      fills.add(stations[i - 1]);
      pos = stations[i - 1].at_m;
      continue;
    }
    const next = i < stations.length ? stations[i].at_m : total;
    short.push({ from_m: pos, to_m: next });
    if (i >= stations.length) break;
    if (total - next > SAME_TOWN_M) fills.add(stations[i]);
    pos = next;
  }
  return { fills, short };
}

const toRad = Math.PI / 180;
function haversine(lat1, lon1, lat2, lon2) {
  const a = Math.sin(((lat2 - lat1) * toRad) / 2) ** 2
    + Math.cos(lat1 * toRad) * Math.cos(lat2 * toRad) * Math.sin(((lon2 - lon1) * toRad) / 2) ** 2;
  return 12742000 * Math.asin(Math.sqrt(a));
}

/** The route's line between two distances along it, as Leaflet latlngs. */
function routeSlice(r, from, to) {
  const coords = r.features.flatMap((f) => f.geometry.coordinates);
  const out = [];
  let d = 0;
  for (let k = 1; k < coords.length; k++) {
    const [plon, plat] = coords[k - 1], [lon, lat] = coords[k];
    const seg = haversine(plat, plon, lat, lon);
    const at = (m) => { const t = seg ? (m - d) / seg : 0; return [plat + (lat - plat) * t, plon + (lon - plon) * t]; };
    if (!out.length && d + seg >= from) out.push(at(from));
    if (d + seg >= to) { out.push(at(to)); break; }
    if (out.length) out.push([lat, lon]);
    d += seg;
  }
  return out;
}

function renderGas(r) {
  fuelShortLayer.clearLayers();
  const fuel = r.fuel;
  $("gas").hidden = $("fuel-info").hidden = !fuel;
  if (!fuel) return;
  const gap = fuel.longest_gap;
  const where = !gap ? "" : gap.from_start && gap.to_end ? "for the whole route"
    : gap.from_start ? `from the start to mile ${mi(gap.to_m)}`
    : gap.to_end ? `from mile ${mi(gap.from_m)} to the end`
    : `between mile ${mi(gap.from_m)} and ${mi(gap.to_m)}`;
  const gapEl = $("gas-gap");
  gapEl.textContent = !fuel.stations.length
    ? `No gas within a mile of this route (${fmtDist(gap?.length_m || 0)}).`
    : `Longest stretch without gas: ${fmtDist(gap.length_m)}, ${where}.`;
  const range = fuelRange * 1609.344;
  gapEl.classList.toggle("warn", (gap?.length_m || 0) > (range || 100 * 1609.34));

  const plan = range ? planFuel(fuel.stations, r.summary.distance_m, range) : { fills: new Set(), short: [] };
  const planEl = $("gas-plan");
  planEl.hidden = !range;
  planEl.classList.toggle("warn", plan.short.length > 0);
  if (plan.short.length) {
    const list = plan.short.slice(0, 3).map((s) => `mile ${mi(s.from_m)}–${mi(s.to_m)} (${fmtDist(s.to_m - s.from_m)})`).join(", ");
    planEl.textContent = `${plan.short.length === 1 ? "1 stretch is" : `${plan.short.length} stretches are`} longer than your ${fuelRange} mi range: ${list}${plan.short.length > 3 ? "…" : ""}. Carry extra fuel; shown in red on the map.`;
  } else if (range) {
    planEl.textContent = plan.fills.size
      ? `Fill up ${plan.fills.size === 1 ? "once" : `${plan.fills.size} times`} to make it on a ${fuelRange} mi range, starting full. Stops are marked below.`
      : `One tank covers it on a ${fuelRange} mi range, starting full.`;
  }
  for (const s of plan.short) {
    fuelShortLayer.addLayer(L.polyline(routeSlice(r, s.from_m, s.to_m), {
      pane: "fuelShort", interactive: false, color: cssVar("--red"), weight: 16, opacity: 0.45, lineCap: "round", lineJoin: "round",
    }));
  }

  // Stations a couple of miles apart along the route (one town) share a row.
  const groups = [];
  for (const st of fuel.stations) {
    const g = groups[groups.length - 1];
    if (g && st.at_m - g[g.length - 1].at_m < 3200) g.push(st);
    else groups.push([st]);
  }
  const ol = $("gas-list");
  ol.innerHTML = "";
  for (const g of groups) {
    const names = [...new Set(g.map((s) => s.name))];
    const off = Math.min(...g.map((s) => s.off_m));
    const fill = g.some((s) => plan.fills.has(s));
    const li = document.createElement("li");
    li.innerHTML = `<span class="gas-ico">${GAS_ICON}</span>
      <span class="name">${esc(names.slice(0, 3).join(", "))}${names.length > 3 ? ` +${names.length - 3}` : ""}
        <small>${off < 200 ? "On route" : `${fmtDist(off)} off route`}${g.length === 1 && gasDetails(g[0]) ? ` · ${gasDetails(g[0])}` : ""}</small></span>
      ${fill ? `<span class="fill" title="Planned fill-up for your fuel range">Fill up</span>` : ""}
      <span class="dist">mile ${mi(g[0].at_m)}</span>`;
    li.addEventListener("click", () => {
      if (!gasOn) setKinds(["gas"], true);
      map.fitBounds(L.latLngBounds(g.map((s) => [s.lat, s.lon])), { maxZoom: 15, padding: [80, 80] });
    });
    ol.appendChild(li);
  }
}
const mi = (m) => Math.round(m / 1609.34).toLocaleString();

// ---------- routing ----------
let routeCtl = null;

async function fetchRoute({ fit }) {
  if (state.stops.some((s) => !s)) {
    state.route = null;
    renderRoute();
    renderStyle();
    return;
  }
  routeCtl?.abort();
  routeCtl = new AbortController();
  setStatus("Finding a route…");
  try {
    const res = await fetch("/api/route", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        points: state.stops.map((p) => [p.lat, p.lon]),
        profile: state.vehicles[0],
        vehicles: state.vehicles,
        legs: state.legs,
      }),
      signal: routeCtl.signal,
    });
    const body = await res.json();
    if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : res.statusText);
    state.route = body;
    setStatus("");
    renderRoute();
    renderStyle();
    if (fit) fitRoute();
    fetchElevation(body);
  } catch (err) {
    if (err.name === "AbortError") return;
    state.route = null;
    renderRoute();
    renderStyle();
    setStatus(err.message, true);
  }
}

function fitRoute() {
  if (!routeLayer.getLayers().length) return;
  const narrow = window.innerWidth <= 640;
  map.fitBounds(routeLayer.getBounds(), narrow
    ? { paddingTopLeft: [24, 60], paddingBottomRight: [24, window.innerHeight * 0.6] }
    : { paddingTopLeft: [60, 70], paddingBottomRight: [80, 50] });
}

function renderRoute() {
  routeLayer.clearLayers();
  fuelShortLayer.clearLayers();
  const r = state.route;
  $("result").hidden = $("summary-box").hidden = !r;
  if (!r) $("fuel-info").hidden = true;
  if (!r) elevCtl?.abort();
  $("hint").hidden = !!r;
  if (!r) return;

  // With several legs, the leg being edited is drawn on top and the others recede.
  const multi = r.legs.length > 1;
  const isActive = (f) => !multi || f.properties.leg === state.activeLeg;
  for (const active of [false, true]) {
    const features = r.features.filter((f) => isActive(f) === active);
    if (features.length) drawLines({ type: "FeatureCollection", features }, renderers[active ? "routeActive" : "routeInactive"]);
  }
  renderSummary(r);
  renderGas(r);
}

function drawLines(fc, renderer) {
  // Dark outline + white halo + color: readable on any basemap, satellite included.
  const outline = L.geoJSON(fc, {
    renderer, interactive: false,
    style: { color: "#2b2b2b", weight: 8.5, opacity: 1, lineCap: "round", lineJoin: "round" },
  });
  const halo = L.geoJSON(fc, {
    renderer, interactive: false,
    style: { color: "#fff", weight: 6.5, opacity: 1, lineCap: "round", lineJoin: "round" },
  });
  const lines = L.geoJSON(fc, {
    renderer,
    style: (f) => {
      const k = KINDS[f.properties.kind] || KINDS.paved;
      return { color: cssVar(k.color), weight: 4, opacity: 1, dashArray: k.dash || null, lineCap: k.dash ? "butt" : "round", lineJoin: "round" };
    },
    onEachFeature: (f, layer) => {
      const k = KINDS[f.properties.kind] || KINDS.paved;
      const details = (f.properties.details || []).map((d) => `<br><small>${esc(d)}</small>`).join("");
      layer.bindTooltip(`${esc(f.properties.name || "Unnamed road")}<br><small>${k.label} · ${fmtDist(f.properties.distance_m)}</small>${details}`, { sticky: true });
      layer.on("mouseover", () => layer.setStyle({ weight: 6 }));
      layer.on("mouseout", () => layer.setStyle({ weight: 4 }));
      layer.on("click", (e) => { L.DomEvent.stopPropagation(e); insertVia(e.latlng, f.properties.leg); });
    },
  });
  routeLayer.addLayer(outline).addLayer(halo).addLayer(lines);
}

function renderSummary(r) {
  const s = r.summary;
  $("sum-time").textContent = fmtTime(s.duration_s);
  $("sum-dist").textContent = fmtDist(s.distance_m);
  $("sum-dirt").textContent = `${Math.round((100 * s.unpaved_m) / Math.max(s.distance_m, 1))}%`;
  const kinds = Object.keys(KINDS).filter((k) => s.by_kind_m[k] > 0);
  $("bar").innerHTML = kinds
    .map((k) => `<span style="width:${(100 * s.by_kind_m[k]) / s.distance_m}%;background:var(${KINDS[k].color})"></span>`).join("");
  $("bar-legend").innerHTML = kinds
    .map((k) => `<span><i style="background:var(${KINDS[k].color})"></i>${KINDS[k].label} ${fmtDist(s.by_kind_m[k])}</span>`).join("");

  const ol = $("steps");
  ol.innerHTML = "";
  for (const st of r.steps) {
    if (st.kind !== "switch" && st.distance_m < 160 && r.steps.length > 12) continue;
    const li = document.createElement("li");
    if (st.kind === "switch") {
      li.className = "switch";
      li.innerHTML = `${PROFILE_ICONS[st.vehicle] || ""}<span class="name">${esc(st.name)}</span>`;
      li.addEventListener("click", () => map.setView(st.start, Math.max(map.getZoom(), 14)));
      ol.appendChild(li);
      continue;
    }
    li.innerHTML = `<span class="swatch" style="background:var(${(KINDS[st.kind] || KINDS.paved).color})"></span>
      <span class="name">${esc(st.name.replace(/^unnamed (\w+)/, (_, t) => `Unnamed ${t}`))}</span><span class="dist">${fmtDist(st.distance_m)}</span>`;
    li.addEventListener("click", () => map.setView(st.start, Math.max(map.getZoom(), 14)));
    ol.appendChild(li);
  }
}

// ---------- theme ----------
function setTheme(theme, save = false) {
  document.documentElement.dataset.theme = theme;
  document.querySelector('meta[name="theme-color"]').content = theme === "dark" ? "#202124" : "#ffffff";
  if (save) store.set("ui.theme", theme);
}
setTheme(document.documentElement.dataset.theme === "light" ? "light" : "dark");
$("theme-toggle").addEventListener("click", () =>
  setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark", true));

// ---------- elevation ----------
let elevCtl = null;
let elevDot = null;
const ft = (m) => `${Math.round(m * 3.28084).toLocaleString()} ft`;

async function fetchElevation(route) {
  elevCtl?.abort();
  elevCtl = new AbortController();
  $("elev").hidden = true;
  const coords = route.features.flatMap((f) => f.geometry.coordinates);
  try {
    const res = await fetch("/api/elevation", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ coords }),
      signal: elevCtl.signal,
    });
    if (!res.ok) return; // offline or tile server down: just skip the card
    const prof = await res.json();
    if (state.route !== route) return;
    renderElevation(prof);
  } catch (err) {
    if (err.name !== "AbortError") console.warn("elevation:", err);
  }
}

function renderElevation(p) {
  $("elev").hidden = false;
  $("el-gain").textContent = `↗ ${ft(p.gain_m)}`;
  $("el-loss").textContent = `↘ ${ft(p.loss_m)}`;
  $("el-max").textContent = ft(p.max_m);
  $("el-grade").textContent = `${Math.round(p.max_grade * 100)}%`;

  const svg = $("el-svg");
  const W = svg.clientWidth || 300, H = 96, pad = 4;
  const s = p.samples;
  const total = s[s.length - 1][0] || 1;
  const lo = p.min_m, hi = Math.max(p.max_m, lo + 50);
  const X = (d) => (d / total) * W;
  const Y = (e) => pad + (1 - (e - lo) / (hi - lo)) * (H - 2 * pad - 12);
  const line = s.map(([d, e], i) => `${i ? "L" : "M"}${X(d).toFixed(1)},${Y(e).toFixed(1)}`).join("");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.innerHTML = `
    <defs><linearGradient id="el-grad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="var(--blue)" stop-opacity="0.45"/>
      <stop offset="1" stop-color="var(--blue)" stop-opacity="0.04"/>
    </linearGradient></defs>
    <path class="area" d="${line}L${W},${H - 12}L0,${H - 12}Z"/>
    <path class="line" d="${line}"/>
    <text class="axis" x="0" y="${H - 1}">${ft(lo)}</text>
    <text class="axis" x="${W}" y="${H - 1}" text-anchor="end">${fmtDist(total)}</text>
    <line class="cursor" y1="0" y2="${H - 12}" visibility="hidden"/>`;

  const cursor = svg.querySelector(".cursor");
  const tip = $("el-tip");
  svg.onmousemove = (ev) => {
    const rect = svg.getBoundingClientRect();
    const d = ((ev.clientX - rect.left) / rect.width) * total;
    let i = Math.round((d / total) * (s.length - 1));
    i = Math.max(0, Math.min(s.length - 1, i));
    const [dist, ele, lat, lon] = s[i];
    const x = X(dist);
    cursor.setAttribute("x1", x);
    cursor.setAttribute("x2", x);
    cursor.setAttribute("visibility", "visible");
    tip.hidden = false;
    tip.style.left = `${(x / W) * 100}%`;
    tip.textContent = `${ft(ele)} · ${fmtDist(dist)}`;
    if (!elevDot) {
      elevDot = L.marker([lat, lon], {
        interactive: false, zIndexOffset: 2000,
        icon: L.divIcon({ className: "", iconSize: [14, 14], iconAnchor: [7, 7], html: '<div class="el-dot"></div>' }),
      }).addTo(map);
    } else {
      elevDot.setLatLng([lat, lon]);
    }
  };
  svg.onmouseleave = () => {
    cursor.setAttribute("visibility", "hidden");
    tip.hidden = true;
    elevDot?.remove();
    elevDot = null;
  };
}

// ---------- GPX ----------
$("gpx").addEventListener("click", () => {
  const r = state.route;
  if (!r) return;
  const pts = [];
  for (const f of r.features) {
    for (const [lon, lat] of f.geometry.coordinates) {
      const last = pts[pts.length - 1];
      if (!last || last[0] !== lat || last[1] !== lon) pts.push([lat, lon]);
    }
  }
  const wpts = state.stops.map((s) =>
    `  <wpt lat="${s.lat.toFixed(6)}" lon="${s.lon.toFixed(6)}"><name>${esc(s.label)}</name></wpt>`).join("\n");
  const trkpts = pts.map(([la, lo]) => `      <trkpt lat="${la.toFixed(6)}" lon="${lo.toFixed(6)}"/>`).join("\n");
  const name = `${state.stops[0].label} to ${state.stops[state.stops.length - 1].label}`;
  const gpx = `<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="GravelMaps" xmlns="http://www.topografix.com/GPX/1/1">
${wpts}
  <trk><name>${esc(name)}</name><trkseg>
${trkpts}
  </trkseg></trk>
</gpx>
`;
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([gpx], { type: "application/gpx+xml" }));
  a.download = `${name.replace(/[^\w\- ]+/g, "").trim().replace(/\s+/g, "-") || "route"}.gpx`;
  a.click();
  URL.revokeObjectURL(a.href);
});

// ---------- URL state ----------
// #pts=lat,lon;lat,lon&v=car,dualsport&l=mostly,dirt   (per leg: a vehicle, and a preset key or 7 dot-separated values)
function writeHash() {
  const p = new URLSearchParams();
  const pts = state.stops.filter(Boolean);
  if (pts.length) p.set("pts", pts.map((s) => `${s.lat.toFixed(5)},${s.lon.toFixed(5)}`).join(";"));
  p.set("v", state.vehicles.join(","));
  p.set("l", state.legs.map((v) => presetOf(v) || v.join(".")).join(","));
  history.replaceState(null, "", `#${p}`);
}

function readHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  const vehicles = (p.get("v") || "").split(",").filter((v) => state.info.profiles[v]);
  if (vehicles.length) state.vehicles = vehicles;
  const pts = (p.get("pts") || "").split(";").filter(Boolean).map((t) => {
    const [lat, lon] = t.split(",").map(Number);
    return { lat, lon, label: fmtLL(lat, lon) };
  });
  if (pts.length === 1) pts.push(null);
  if (pts.length >= 2) state.stops = pts;
  const n = kindKeys().length + 1; // road kinds, then High Elevation
  state.legs = (p.get("l") || "").split(",").filter(Boolean).map((t) => {
    if (state.info.presets[t]) return presetValues(t);
    const v = t.split(".").map(Number);
    if (v.length === n - 1) v.push(50); // links from before the elevation slider
    return v.length === n && v.every((x) => x >= 0 && x <= 100) ? v : defaultLeg();
  });
}

function update({ fit = false } = {}) {
  syncLegs();
  renderProfiles();
  renderStops();
  renderMarkers();
  renderStyle();
  writeHash();
  fetchRoute({ fit });
}

// ---------- boot ----------
(async function init() {
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
})();
