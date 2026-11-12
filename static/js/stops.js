// Stops: the input rows, their map markers, clicking the map to set them, and "my location".

import { $, esc, fmtLL, setStatus } from "./util.js";
import { dropIndex, insertStop, moveStop, state, stopRole } from "./state.js";
import { map, markerLayer } from "./map.js";
import { attachSearch } from "./search.js";
import { showMvumInfo } from "./mvum.js";
import { update } from "./main.js";

function removeStop(i) {
  state.stops.splice(i, 1);
  for (const arr of [state.legs, state.vehicles]) {
    if (i === 0) arr.shift();
    else arr.splice(i, 1); // merge legs i-1 and i, keeping i-1's style and vehicle
  }
  if (state.stops.length < 2) state.stops.push(null);
  update();
}

export function renderStops() {
  const box = $("stops");
  box.innerHTML = "";
  state.stops.forEach((s, i) => {
    const role = stopRole(i);
    const row = document.createElement("div");
    row.className = "stop";
    const ph = role === "start" ? "Start — or “Big Sur to Monterey”" : role === "end" ? "Destination" : "Stop";
    row.innerHTML = `
      <span class="handle" title="Drag to reorder"><span class="dot ${role}">${role === "via" ? i : ""}</span>
        <svg class="grip" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M9 5.5a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0zm0 6.5a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0zm-1.5 8a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zM18 5.5a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0zM16.5 13.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zM18 18.5a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0z"/></svg></span>
      <input type="text" placeholder="${ph}" value="${s ? esc(s.label) : ""}" autocomplete="off" spellcheck="false" enterkeyhint="search">
      ${role === "via" ? `<button class="remove" aria-label="Remove stop">✕</button>` : ""}`;
    attachSearch(row.querySelector("input"), row, i);
    row.querySelector(".remove")?.addEventListener("click", () => removeStop(i));
    row.querySelector(".handle").addEventListener("pointerdown", (ev) => startDrag(ev, row, i));
    box.appendChild(row);
  });
}

// ---------- drag a stop row up or down to reorder, like Google Maps ----------
function startDrag(ev, row, from) {
  if (ev.button !== 0) return;
  ev.preventDefault();
  const box = $("stops");
  const rows = [...box.children];
  const rects = rows.map((r) => r.getBoundingClientRect());
  const pitch = rects.length > 1 ? rects[1].top - rects[0].top : rects[0].height;
  const startY = ev.clientY;
  const centre0 = rects[from].top + rects[from].height / 2;
  const mids = rects.filter((_, k) => k !== from).map((r) => r.top + r.height / 2);
  const first = rects[0].top, last = rects[rects.length - 1].top;
  let to = from, moved = false;

  const handle = ev.currentTarget;
  handle.setPointerCapture(ev.pointerId);
  const move = (e) => {
    const dy = Math.max(first - rects[from].top, Math.min(last - rects[from].top, e.clientY - startY));
    if (!moved && Math.abs(dy) < 4) return; // a click, not a drag
    if (!moved) { moved = true; box.classList.add("dragging"); row.classList.add("lifted"); }
    row.style.transform = `translateY(${dy}px)`;
    to = dropIndex(centre0 + dy, mids);
    // Make room: rows between the old and new place slide one row over.
    rows.forEach((r, k) => {
      if (k === from) return;
      const shift = from < to && k > from && k <= to ? -pitch : from > to && k >= to && k < from ? pitch : 0;
      r.style.transform = shift ? `translateY(${shift}px)` : "";
    });
  };
  const end = () => {
    handle.removeEventListener("pointermove", move);
    handle.removeEventListener("pointerup", end);
    handle.removeEventListener("pointercancel", end);
    box.classList.remove("dragging");
    rows.forEach((r) => { r.style.transform = ""; r.classList.remove("lifted"); });
    if (moved && moveStop(from, to)) update();
  };
  handle.addEventListener("pointermove", move);
  handle.addEventListener("pointerup", end);
  handle.addEventListener("pointercancel", end);
}

let meMarker = null;
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

function pinIcon(i) {
  const role = stopRole(i);
  if (role === "start") return L.divIcon({ className: "", iconSize: [20, 20], iconAnchor: [10, 10], html: '<div class="pin-start"></div>' });
  if (role === "end") return L.divIcon({ className: "", iconSize: [30, 40], iconAnchor: [15, 40], html: '<div class="pin-end"><div class="head"></div><div class="stem"></div></div>' });
  return L.divIcon({ className: "", iconSize: [22, 22], iconAnchor: [11, 11], html: `<div class="pin-via">${i}</div>` });
}

export function renderMarkers() {
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

export function insertVia(latlng, leg) {
  insertStop(leg + 1, { lat: latlng.lat, lon: latlng.lng, label: fmtLL(latlng.lat, latlng.lng) });
  update();
}

export function initStops() {
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
  $("locate-me").addEventListener("click", () => locate(true));
  map.on("click", async (e) => {
    if (await showMvumInfo(e.latlng)) return; // with MVUM on, a click on a forest road shows who may drive it
    const i = state.stops.findIndex((s) => !s);
    if (i < 0) return;
    state.stops[i] = { lat: e.latlng.lat, lon: e.latlng.lng, label: fmtLL(e.latlng.lat, e.latlng.lng) };
    update();
  });
}
