// Forest Service motor vehicle use maps: the key, and details for a clicked road or trail.

import { esc } from "./util.js";
import { map } from "./map.js";
import { PIN_POPUP, placePopup } from "./pois.js";
import { FS_EDW, overlaysOn } from "./overlays.js";
import { campingAt } from "./camping.js";
import { renderMarkerPanel } from "./markerPanel.js";

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

export function mvumKeyHtml() {
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

export async function showMvumInfo(latlng) {
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
