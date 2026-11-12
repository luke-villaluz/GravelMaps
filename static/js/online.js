// Whether the outside internet is reachable. Routing, search of OSM places, camping and the
// downloaded street map work without it; satellite and topo basemaps, the land agencies' overlays
// and address search don't, so the UI greys those out instead of drawing blank tiles.

const listeners = new Set();
export const net = { online: navigator.onLine };
export const onNetChange = (fn) => listeners.add(fn);

function set(online) {
  if (online === net.online) return;
  net.online = online;
  listeners.forEach((fn) => fn(online));
}

// navigator.onLine only knows whether there is a network, not whether it reaches the internet
// (a hotel login page, a phone hotspot with no signal), so ask a server we use anyway.
async function probe() {
  if (!navigator.onLine) return set(false);
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 6000);
  try {
    await fetch("https://server.arcgisonline.com/ArcGIS/rest/info?f=json", { mode: "no-cors", cache: "no-store", signal: ctl.signal });
    set(true);
  } catch {
    set(false);
  } finally {
    clearTimeout(timer);
  }
}

export function initNet() {
  window.addEventListener("online", probe);
  window.addEventListener("offline", () => set(false));
  probe();
  setInterval(probe, 60_000);
}

// The basemap to draw: the chosen one, unless it needs the internet and we're offline, in which
// case the offline street map (when downloaded). The choice itself is kept for when we're back.
export function shownBasemap(chosen, basemaps, online) {
  if (online || !basemaps[chosen]?.needsNet()) return chosen;
  return Object.keys(basemaps).find((k) => !basemaps[k].needsNet()) || chosen;
}
