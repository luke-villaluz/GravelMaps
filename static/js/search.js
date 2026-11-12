// Place search in the stop boxes: suggestions, keyboard picking, and "A to B".

import { $, esc, setStatus } from "./util.js";
import { state } from "./state.js";
import { map } from "./map.js";
import { update } from "./main.js";
import { net } from "./online.js";

let searchCtl = null;

async function geocode(q, remote = true) {
  searchCtl?.abort();
  searchCtl = new AbortController();
  const c = map.getCenter();
  // Offline, only the downloaded OSM places are searched: no waiting on a geocoder that can't answer.
  const res = await fetch(`/api/geocode?q=${encodeURIComponent(q)}&lat=${c.lat.toFixed(4)}&lon=${c.lng.toFixed(4)}&remote=${remote && net.online}`,
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

export function attachSearch(input, row, i) {
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
        state.vehicles = [state.vehicles[0]];
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
