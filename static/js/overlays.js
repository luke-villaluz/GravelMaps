// Map overlays from the land agencies' own map services.

import { store } from "./util.js";
import { map } from "./map.js";
import { CampingLayer } from "./camping.js";
import { renderMarkerPanel } from "./markerPanel.js";
import { net, onNetChange } from "./online.js";

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
export const FS_EDW = "https://apps.fs.usda.gov/arcx/rest/services/EDW";
const BLM_SMA = "https://gis.blm.gov/arcgis/rest/services/lands/BLM_Natl_SMA_Cached_without_PriUnk/MapServer";
// The BLM's own colours for who manages the land; private land is left clear.
export const LAND_KEY = [["BLM", "#fee679"], ["Forest Service", "#ccebc5"], ["National Park", "#cabddc"], ["State", "#b3e3ee"],
  ["Fish & Wildlife", "#7fcca7"], ["Military", "#fbb4ce"], ["Tribal", "#fdb46c"], ["Reclamation", "#ffffb3"],
  ["Other federal", "#e4c49f"], ["Local", "#8fb5be"]];
export const OVERLAYS = [
  { key: "land", label: "Public land", swatch: "land", needsNet: true,
    note: "Who manages the land. BLM land is usually open to dispersed camping; private land is left clear.",
    make: () => L.tileLayer(`${BLM_SMA}/tile/{z}/{y}/{x}`, { pane: "land", opacity: 0.55, maxNativeZoom: 14, maxZoom: 19, attribution: "Land status: BLM" }) },
  { key: "wilderness", label: "Wilderness areas", swatch: "wilderness", needsNet: true,
    note: "No motor vehicles or bikes inside wilderness boundaries.",
    make: () => new ArcGISLayer(`${FS_EDW}/EDW_Wilderness_01/MapServer`, { layers: "show:0", pane: "land", opacity: 0.6, maxZoom: 19, attribution: "Wilderness: USDA Forest Service" }) },
  { key: "forests", label: "Forest boundaries", swatch: "forests", needsNet: true,
    make: () => new ArcGISLayer(`${FS_EDW}/EDW_ForestSystemBoundaries_01/MapServer`, { layers: "show:0,1", pane: "lines", maxZoom: 19, attribution: "Forest boundaries: USDA Forest Service" }) },
  { key: "mvum", label: "MVUM roads & trails", swatch: "mvum", minZoom: 10, needsNet: true,
    note: "Forest Service motor vehicle use maps, from zoom 10. The numbers are Forest Service road and trail numbers; click one for the vehicles allowed and dates open. Not every forest publishes this data.",
    // Big tiles: labels are cut at tile edges, so fewer edges means fewer cut-off road numbers.
    make: () => new ArcGISLayer(`${FS_EDW}/EDW_MVUM_01/MapServer`, { layers: "show:1,2", pane: "lines", tileSize: 512, dpi: 240, minZoom: 10, maxZoom: 19, attribution: "MVUM: USDA Forest Service" }) },
  { key: "camping", label: "Dispersed camping", swatch: "camping", minZoom: 9,
    note: "Read from each forest's printed motor vehicle use maps, from zoom 9. Click a line or area for the rules and the source map. Works offline.",
    make: () => new CampingLayer() },
];
map.createPane("land").style.zIndex = 210;  // fills: over the basemap, under our road overlay and the route
map.createPane("lines").style.zIndex = 260; // boundaries and MVUM lines: over our road overlay
export const overlaysOn = new Set((() => { try { return JSON.parse(store.get("overlays") || "[]"); } catch { return []; } })());
const overlayLayers = {};

export function setOverlay(key, on) {
  if (on) overlaysOn.add(key);
  else overlaysOn.delete(key);
  store.set("overlays", JSON.stringify([...overlaysOn]));
  syncOverlays();
  renderMarkerPanel();
}
function syncOverlays() {
  for (const o of OVERLAYS) {
    // Agency overlays stay switched on while offline, but only draw once the internet is back.
    const on = overlaysOn.has(o.key) && !overlayBlocked(o);
    if (on && !overlayLayers[o.key]) overlayLayers[o.key] = o.make().addTo(map);
    if (!on && overlayLayers[o.key]) { overlayLayers[o.key].remove(); delete overlayLayers[o.key]; }
  }
}

export const overlayBlocked = (o) => Boolean(o.needsNet) && !net.online;

export function initOverlays() {
  syncOverlays();
  onNetChange(() => { syncOverlays(); renderMarkerPanel(); });
  map.on("zoomend", () => { if (OVERLAYS.some((o) => o.minZoom && overlaysOn.has(o.key))) renderMarkerPanel(); }); // overlays' "zoom in" notes
}
