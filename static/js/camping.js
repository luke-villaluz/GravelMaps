// Dispersed camping: rules read from the forests' MVUM PDFs (gravelmaps/camping.py).

import { esc } from "./util.js";
import { state } from "./state.js";
import { map } from "./map.js";
import { PIN_POPUP, placePopup } from "./pois.js";

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

export async function campingAt(lat, lon) {
  try { return await (await fetch(`/api/camping/at?lat=${lat}&lon=${lon}`)).json(); } catch { return null; }
}

export const CampingLayer = L.LayerGroup.extend({
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

export function campKeyHtml() {
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
