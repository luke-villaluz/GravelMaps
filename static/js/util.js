// Small helpers shared by every module: DOM lookup, storage, formatting.

export const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
export const $ = (id) => document.getElementById(id);
export const store = {
  get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
};

// ---------- helpers ----------
export const fmtDist = (m) => {
  const mi = m / 1609.344;
  return mi < 0.1 ? `${Math.round(m * 3.28084)} ft` : mi < 10 ? `${mi.toFixed(1)} mi` : `${Math.round(mi)} mi`;
};
export const fmtTime = (s) => {
  const h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60);
  return h ? `${h} hr ${m} min` : `${m} min`;
};
export const fmtTimeShort = (s) => {
  const h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m`;
};
export const fmtLL = (lat, lon) => `${lat.toFixed(5)}, ${lon.toFixed(5)}`;
export const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

export function setStatus(msg, isError = false) {
  const el = $("status");
  el.hidden = !msg;
  el.textContent = msg || "";
  el.classList.toggle("error", isError);
}

export const mi = (m) => Math.round(m / 1609.34).toLocaleString();
