// The Leaflet map, its basemaps and the layers the other modules draw into.

import { $, store } from "./util.js";
import { state } from "./state.js";

// Explicit zoom limits: otherwise Leaflet borrows them from tile layers, and while basemaps are
// swapped the dirt overlay's minZoom of 13 briefly becomes the map's and yanks the view in.
export const map = L.map("map", { zoomControl: false, minZoom: 3, maxZoom: 19 }).setView([39.5, -117], 6);
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
export function setBasemap(key, save = false) {
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

// Inactive legs render into their own pane, faded as a whole so overlapping line caps don't stack.
for (const [name, z] of [["routeInactive", 410], ["routeActive", 420]]) map.createPane(name).style.zIndex = z;
map.getPane("routeInactive").style.opacity = 0.4;
export const renderers = { routeInactive: L.svg({ pane: "routeInactive" }), routeActive: L.svg({ pane: "routeActive" }) };
export const routeLayer = L.featureGroup().addTo(map);
// Stretches longer than the fuel range: a red band under the route.
map.createPane("fuelShort").style.zIndex = 405;
export const fuelShortLayer = L.layerGroup().addTo(map);
export const markerLayer = L.layerGroup().addTo(map);

export function initMap() {
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
}
