// The elevation profile card under a route.

import { $, fmtDist } from "./util.js";
import { state } from "./state.js";
import { map } from "./map.js";

let elevCtl = null;
let elevDot = null;
const ft = (m) => `${Math.round(m * 3.28084).toLocaleString()} ft`;

export async function fetchElevation(route) {
  elevCtl?.abort();
  elevCtl = new AbortController();
  $("elev").hidden = true;
  const coords = route.features.flatMap((f) => f.geometry.coordinates);
  try {
    const res = await fetch("/api/elevation", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ coords }),
      signal: elevCtl.signal,
    });
    if (!res.ok) return; // offline or tile server down: just skip the card
    const prof = await res.json();
    if (state.route !== route) return;
    renderElevation(prof);
  } catch (err) {
    if (err.name !== "AbortError") console.warn("elevation:", err);
  }
}

function renderElevation(p) {
  $("elev").hidden = false;
  $("el-gain").textContent = `↗ ${ft(p.gain_m)}`;
  $("el-loss").textContent = `↘ ${ft(p.loss_m)}`;
  $("el-max").textContent = ft(p.max_m);
  $("el-grade").textContent = `${Math.round(p.max_grade * 100)}%`;

  const svg = $("el-svg");
  const W = svg.clientWidth || 300, H = 96, pad = 4;
  const s = p.samples;
  const total = s[s.length - 1][0] || 1;
  const lo = p.min_m, hi = Math.max(p.max_m, lo + 50);
  const X = (d) => (d / total) * W;
  const Y = (e) => pad + (1 - (e - lo) / (hi - lo)) * (H - 2 * pad - 12);
  const line = s.map(([d, e], i) => `${i ? "L" : "M"}${X(d).toFixed(1)},${Y(e).toFixed(1)}`).join("");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.innerHTML = `
    <defs><linearGradient id="el-grad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="var(--blue)" stop-opacity="0.45"/>
      <stop offset="1" stop-color="var(--blue)" stop-opacity="0.04"/>
    </linearGradient></defs>
    <path class="area" d="${line}L${W},${H - 12}L0,${H - 12}Z"/>
    <path class="line" d="${line}"/>
    <text class="axis" x="0" y="${H - 1}">${ft(lo)}</text>
    <text class="axis" x="${W}" y="${H - 1}" text-anchor="end">${fmtDist(total)}</text>
    <line class="cursor" y1="0" y2="${H - 12}" visibility="hidden"/>`;

  const cursor = svg.querySelector(".cursor");
  const tip = $("el-tip");
  svg.onmousemove = (ev) => {
    const rect = svg.getBoundingClientRect();
    const d = ((ev.clientX - rect.left) / rect.width) * total;
    let i = Math.round((d / total) * (s.length - 1));
    i = Math.max(0, Math.min(s.length - 1, i));
    const [dist, ele, lat, lon] = s[i];
    const x = X(dist);
    cursor.setAttribute("x1", x);
    cursor.setAttribute("x2", x);
    cursor.setAttribute("visibility", "visible");
    tip.hidden = false;
    tip.style.left = `${(x / W) * 100}%`;
    tip.textContent = `${ft(ele)} · ${fmtDist(dist)}`;
    if (!elevDot) {
      elevDot = L.marker([lat, lon], {
        interactive: false, zIndexOffset: 2000,
        icon: L.divIcon({ className: "", iconSize: [14, 14], iconAnchor: [7, 7], html: '<div class="el-dot"></div>' }),
      }).addTo(map);
    } else {
      elevDot.setLatLng([lat, lon]);
    }
  };
  svg.onmouseleave = () => {
    cursor.setAttribute("visibility", "hidden");
    tip.hidden = true;
    elevDot?.remove();
    elevDot = null;
  };
}

export function abortElevation() {
  elevCtl?.abort();
}
