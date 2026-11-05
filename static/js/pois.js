// Gas stations and points of interest: pins, hover cards, popups and which kinds are shown.

import { esc, fmtLL, store } from "./util.js";
import { insertStop, state } from "./state.js";
import { GAS_ICON, POI_ICONS } from "./icons.js";
import { map } from "./map.js";
import { renderMarkerPanel } from "./markerPanel.js";
import { update } from "./main.js";

const gasLayer = L.layerGroup().addTo(map);
const gasIcon = L.divIcon({ className: "", iconSize: [24, 24], iconAnchor: [12, 12], html: `<div class="gas-pin">${GAS_ICON}</div>` });
let gasOn = store.get("gas") !== "0";
let gasCtl = null;

export function gasDetails(st) {
  const bits = [];
  if (st.brand) bits.push(esc(st.brand));
  if (st.hours) bits.push(st.hours === "24/7" ? "Open 24 hours" : esc(st.hours));
  if (st.diesel === 1) bits.push("Diesel");
  else if (st.diesel === 0) bits.push("No diesel");
  return bits.join(" · ");
}

// A map pin's popup: title, detail lines (HTML), and a button that routes through the place.
// Also the place's coordinates, to copy or open in Google Maps.
export function placePopup(p, title, lines) {
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

export const POI_LABELS = {
  water: "Drinking water", spring: "Spring", campground: "Campground", dispersed: "Dispersed camping",
  rv: "RV park", cabin: "Backcountry cabin", trailhead: "Trailhead", staging: "OHV staging area",
  hotel: "Hotel", motel: "Motel", inn: "Guest house / B&B", hostel: "Hostel", rental: "Cabin or vacation rental",
  ghost_town: "Ghost town", mine: "Mine", ruins: "Ruins", viewpoint: "Viewpoint", peak: "Peak",
  lookout: "Fire lookout", hot_spring: "Hot spring", arch: "Arch", cave: "Cave", petroglyph: "Petroglyphs",
};
// The marker panel on the right: one row per pin type, grouped. Click a row to show or hide that
// type, a group heading for the whole group. Sights get small pins: there are thousands of peaks.
export const MARKER_GROUPS = [
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
export const isOn = (kind) => (kind === "gas" ? gasOn : !poiOff.has(kind));
const poiLayer = L.layerGroup().addTo(map);
const poiIcons = {};
let poiCtl = null;

export function setKinds(kinds, on) {
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
export const PIN_POPUP = { closeButton: true, autoPanPadding: [60, 60] };

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

export function initPois() {
  map.on("moveend", loadGas);
  map.on("moveend", loadPois);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !e.target.closest("input, textarea")) map.closePopup();
  });
  setGas(gasOn);
  loadPois();
}
