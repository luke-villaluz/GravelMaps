"use strict";

// Display info per road kind; keys match the server's KINDS. Order = legend order.
const KINDS = {
  unpaved: { label: "Dirt / Gravel", color: "--k-unpaved" },
  rough: { label: "Rough / 4x4", color: "--k-rough", dash: "6 5" },
  trail: { label: "Trail", color: "--k-trail", dash: "2 6" },
  unknown: { label: "Surface Unknown", color: "--k-unknown" },
  paved: { label: "Paved", color: "--k-paved" },
  major: { label: "Major Road", color: "--k-major" },
  highway: { label: "Highway", color: "--k-highway" },
};
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const $ = (id) => document.getElementById(id);
const dark = window.matchMedia("(prefers-color-scheme: dark)");
const store = {
  get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
};

const state = {
  stops: [null, null], // each: {lat, lon, label} or null
  legs: [], // slider values per leg (arrays in server kind order)
  activeLeg: 0,
  profile: "car",
  route: null,
  basemap: store.get("basemap") || "map",
  info: null, // /api/region: profiles, kinds, presets
};

// ---------- map ----------
const map = L.map("map", { zoomControl: false }).setView([39.5, -117], 6);
L.control.scale({ imperial: true, metric: false, position: "bottomleft" }).addTo(map);
map.attributionControl.setPrefix(false);

const esri = (svc) => `https://server.arcgisonline.com/ArcGIS/rest/services/${svc}/MapServer/tile/{z}/{y}/{x}`;
// Road overlays rendered by our server from the routing graph (see gravelmaps/tiles.py).
const roadLayer = (layer, theme, minZoom, zIndex) =>
  L.tileLayer(`/api/roads/${layer}/{z}/{x}/{y}.png?theme=${theme}&v=${state.info?.tile_version || 0}`, { minZoom, maxZoom: 19, zIndex });
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
const baseGroup = L.layerGroup().addTo(map);

function setBasemap(key) {
  if (!BASEMAPS[key]) key = "map";
  state.basemap = key;
  store.set("basemap", key);
  $("map").dataset.base = key;
  baseGroup.clearLayers();
  BASEMAPS[key].layers().forEach((l) => baseGroup.addLayer(l));
  // Subdued dirt-road detail for close-up looks; the basemaps leave most of these out.
  baseGroup.addLayer(roadLayer("dirt", key === "satellite" ? "light" : "dark", 13, 5));
  $("basemaps").querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.key === key));
}
for (const [key, b] of Object.entries(BASEMAPS)) {
  const btn = document.createElement("button");
  btn.textContent = b.label;
  btn.dataset.key = key;
  btn.addEventListener("click", () => setBasemap(key));
  $("basemaps").appendChild(btn);
}
setBasemap(state.basemap);

$("zoom-in").addEventListener("click", () => map.zoomIn());
$("zoom-out").addEventListener("click", () => map.zoomOut());
$("legend").innerHTML = Object.values(KINDS)
  .map((k) => `<div><i style="background:var(${k.color})"></i>${k.label}</div>`).join("");

// Inactive legs render into their own pane, faded as a whole so overlapping line caps don't stack.
for (const [name, z] of [["routeInactive", 410], ["routeActive", 420]]) map.createPane(name).style.zIndex = z;
map.getPane("routeInactive").style.opacity = 0.4;
const renderers = { routeInactive: L.svg({ pane: "routeInactive" }), routeActive: L.svg({ pane: "routeActive" }) };
const routeLayer = L.featureGroup().addTo(map);
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
const presetOf = (values) =>
  Object.keys(state.info.presets).find((k) => state.info.presets[k].values.every((v, i) => v === values[i])) || null;

function syncLegs() {
  const n = Math.max(1, state.stops.length - 1);
  while (state.legs.length < n) state.legs.push([...(state.legs[state.legs.length - 1] || defaultLeg())]);
  state.legs.length = n;
  state.activeLeg = Math.min(state.activeLeg, n - 1);
}

function insertStop(i, stop) {
  // A new stop splits leg i-1 in two; both halves keep its style.
  state.stops.splice(i, 0, stop);
  state.legs.splice(i - 1, 0, [...state.legs[i - 1]]);
}

function removeStop(i) {
  state.stops.splice(i, 1);
  if (i === 0) state.legs.shift();
  else state.legs.splice(i, 1); // merge legs i-1 and i, keeping i-1's style
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
      b.innerHTML = `<b>${stopLetter(i)} → ${stopLetter(i + 1)}</b><small>${esc(sub)}</small>`;
      b.addEventListener("click", () => { state.activeLeg = i; renderStyle(); renderRoute(); });
      tabs.appendChild(b);
    });
  }

  const chips = $("presets");
  chips.innerHTML = "";
  const current = presetOf(active);
  for (const [key, p] of Object.entries(state.info.presets)) {
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
  const allowed = state.info.profiles[state.profile].kinds;
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
  state.activeLeg = state.legs.length - 1 - state.activeLeg;
  update();
});
$("clear").addEventListener("click", () => {
  state.stops = [null, null];
  state.legs = [state.legs[state.activeLeg]];
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
function renderProfiles() {
  const box = $("profiles");
  box.innerHTML = "";
  for (const [key, p] of Object.entries(state.info.profiles)) {
    const b = document.createElement("button");
    b.textContent = p.label;
    b.setAttribute("role", "tab");
    b.classList.toggle("on", key === state.profile);
    b.addEventListener("click", () => {
      if (state.profile === key) return;
      state.profile = key;
      renderProfiles();
      update();
    });
    box.appendChild(b);
  }
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

map.on("click", (e) => {
  const i = state.stops.findIndex((s) => !s);
  if (i < 0) return;
  state.stops[i] = { lat: e.latlng.lat, lon: e.latlng.lng, label: fmtLL(e.latlng.lat, e.latlng.lng) };
  update();
});

function insertVia(latlng, leg) {
  insertStop(leg + 1, { lat: latlng.lat, lon: latlng.lng, label: fmtLL(latlng.lat, latlng.lng) });
  update();
}

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
        profile: state.profile,
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
    : { paddingTopLeft: [396, 50], paddingBottomRight: [140, 50] });
}

function renderRoute() {
  routeLayer.clearLayers();
  const r = state.route;
  $("result").hidden = !r;
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
      layer.bindTooltip(`${esc(f.properties.name || "Unnamed road")}<br><small>${k.label} · ${fmtDist(f.properties.distance_m)}</small>`, { sticky: true });
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
    if (st.distance_m < 160 && r.steps.length > 12) continue;
    const li = document.createElement("li");
    li.innerHTML = `<span class="swatch" style="background:var(${(KINDS[st.kind] || KINDS.paved).color})"></span>
      <span class="name">${esc(st.name.replace(/^unnamed (\w+)/, (_, t) => `Unnamed ${t}`))}</span><span class="dist">${fmtDist(st.distance_m)}</span>`;
    li.addEventListener("click", () => map.setView(st.start, Math.max(map.getZoom(), 14)));
    ol.appendChild(li);
  }
}

dark.addEventListener("change", () => { setBasemap(state.basemap); renderRoute(); });

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
// #pts=lat,lon;lat,lon&v=car&l=mostly,dirt   (a leg is a preset key or 7 dot-separated values)
function writeHash() {
  const p = new URLSearchParams();
  const pts = state.stops.filter(Boolean);
  if (pts.length) p.set("pts", pts.map((s) => `${s.lat.toFixed(5)},${s.lon.toFixed(5)}`).join(";"));
  p.set("v", state.profile);
  p.set("l", state.legs.map((v) => presetOf(v) || v.join(".")).join(","));
  history.replaceState(null, "", `#${p}`);
}

function readHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  if (p.get("v") && state.info.profiles[p.get("v")]) state.profile = p.get("v");
  const pts = (p.get("pts") || "").split(";").filter(Boolean).map((t) => {
    const [lat, lon] = t.split(",").map(Number);
    return { lat, lon, label: fmtLL(lat, lon) };
  });
  if (pts.length === 1) pts.push(null);
  if (pts.length >= 2) state.stops = pts;
  const n = kindKeys().length;
  state.legs = (p.get("l") || "").split(",").filter(Boolean).map((t) => {
    if (state.info.presets[t]) return presetValues(t);
    const v = t.split(".").map(Number);
    return v.length === n && v.every((x) => x >= 0 && x <= 100) ? v : defaultLeg();
  });
}

function update({ fit = false } = {}) {
  syncLegs();
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
  if (!state.stops.some(Boolean)) map.fitBounds([[s, w], [n, e]], { paddingTopLeft: [380, 0] });
  const names = state.info.regions.map((r) => r.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()));
  $("regions").textContent = `Map data © OpenStreetMap contributors · ${names.join(", ")}`;
  update({ fit: state.stops.some(Boolean) });
})();
