// Fetching a route and drawing it: lines, summary and turn list.

import { $, cssVar, esc, fmtDist, fmtTime, setStatus } from "./util.js";
import { KINDS, state } from "./state.js";
import { PROFILE_ICONS } from "./icons.js";
import { fuelShortLayer, map, renderers, routeLayer } from "./map.js";
import { insertVia } from "./stops.js";
import { renderStyle } from "./style.js";
import { renderGas } from "./fuel.js";
import { abortElevation, fetchElevation } from "./elevation.js";

let routeCtl = null;

export async function fetchRoute({ fit }) {
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

export function renderRoute() {
  routeLayer.clearLayers();
  fuelShortLayer.clearLayers();
  const r = state.route;
  $("result").hidden = $("summary-box").hidden = !r;
  if (!r) $("fuel-info").hidden = true;
  if (!r) abortElevation();
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

export function initRoute() {
  $("legend").innerHTML = Object.values(KINDS)
    .map((k) => `<div><i style="background:var(${k.color})"></i>${k.label}</div>`).join("");
}
