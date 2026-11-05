// GPX export of the current route.

import { $, esc } from "./util.js";
import { state } from "./state.js";

export function initGpx() {
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
}
