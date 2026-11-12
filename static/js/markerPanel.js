// The Map Markers and Map Overlays cards on the right of the map.

import { $, store } from "./util.js";
import { GAS_ICON, POI_ICONS } from "./icons.js";
import { map } from "./map.js";
import { isOn, MARKER_GROUPS, POI_LABELS, setKinds } from "./pois.js";
import { LAND_KEY, OVERLAYS, overlayBlocked, overlaysOn, setOverlay } from "./overlays.js";
import { campKeyHtml } from "./camping.js";
import { mvumKeyHtml } from "./mvum.js";

export function renderMarkerPanel() {
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
      <div class="panel-body">${OVERLAYS.map((o) => `<button class="item${overlaysOn.has(o.key) ? "" : " off"}${overlayBlocked(o) ? " no-net" : ""}" data-overlay="${o.key}" aria-pressed="${overlaysOn.has(o.key)}"${overlayBlocked(o) ? ' title="Needs internet"' : ""}>
        <span class="ov-swatch ov-${o.swatch}"></span>${o.label}${overlayBlocked(o) ? '<small class="no-net-tag">needs internet</small>' : ""}</button>
        ${overlaysOn.has(o.key) && overlayBlocked(o) ? '<p class="ov-note">Comes back when you\'re online again.</p>'
          : overlaysOn.has(o.key) && o.note ? `<p class="ov-note">${o.note}${o.minZoom && z < o.minZoom ? " <b>Zoom in to see it.</b>" : ""}</p>` : ""}
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
