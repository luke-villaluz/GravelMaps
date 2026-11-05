// Gas along the route: the fuel range setting, fill-up plan and station list.

import { $, cssVar, esc, fmtDist, mi, store } from "./util.js";
import { planFuel, routeSlice } from "./geo.js";
import { state } from "./state.js";
import { GAS_ICON } from "./icons.js";
import { fuelShortLayer, map } from "./map.js";
import { gasDetails, isOn, setKinds } from "./pois.js";

// Fuel range: miles on a tank, 0 = off. Fill-ups are planned from the stations along the route.
let fuelRange = Math.min(1000, Math.max(0, +store.get("fuel-range") || 0));
function showFuelRange() {
  const input = $("fuel-range");
  input.value = fuelRange;
  input.style.setProperty("--pct", `${fuelRange / 10}%`);
  $("fuel-range-val").textContent = fuelRange ? `${fuelRange} mi` : "Off";
}

export function renderGas(r) {
  fuelShortLayer.clearLayers();
  const fuel = r.fuel;
  $("gas").hidden = $("fuel-info").hidden = !fuel;
  if (!fuel) return;
  const gap = fuel.longest_gap;
  const where = !gap ? "" : gap.from_start && gap.to_end ? "for the whole route"
    : gap.from_start ? `from the start to mile ${mi(gap.to_m)}`
    : gap.to_end ? `from mile ${mi(gap.from_m)} to the end`
    : `between mile ${mi(gap.from_m)} and ${mi(gap.to_m)}`;
  const gapEl = $("gas-gap");
  gapEl.textContent = !fuel.stations.length
    ? `No gas within a mile of this route (${fmtDist(gap?.length_m || 0)}).`
    : `Longest stretch without gas: ${fmtDist(gap.length_m)}, ${where}.`;
  const range = fuelRange * 1609.344;
  gapEl.classList.toggle("warn", (gap?.length_m || 0) > (range || 100 * 1609.34));

  const plan = range ? planFuel(fuel.stations, r.summary.distance_m, range) : { fills: new Set(), short: [] };
  const planEl = $("gas-plan");
  planEl.hidden = !range;
  planEl.classList.toggle("warn", plan.short.length > 0);
  if (plan.short.length) {
    const list = plan.short.slice(0, 3).map((s) => `mile ${mi(s.from_m)}–${mi(s.to_m)} (${fmtDist(s.to_m - s.from_m)})`).join(", ");
    planEl.textContent = `${plan.short.length === 1 ? "1 stretch is" : `${plan.short.length} stretches are`} longer than your ${fuelRange} mi range: ${list}${plan.short.length > 3 ? "…" : ""}. Carry extra fuel; shown in red on the map.`;
  } else if (range) {
    planEl.textContent = plan.fills.size
      ? `Fill up ${plan.fills.size === 1 ? "once" : `${plan.fills.size} times`} to make it on a ${fuelRange} mi range, starting full. Stops are marked below.`
      : `One tank covers it on a ${fuelRange} mi range, starting full.`;
  }
  for (const s of plan.short) {
    fuelShortLayer.addLayer(L.polyline(routeSlice(r, s.from_m, s.to_m), {
      pane: "fuelShort", interactive: false, color: cssVar("--red"), weight: 16, opacity: 0.45, lineCap: "round", lineJoin: "round",
    }));
  }

  // Stations a couple of miles apart along the route (one town) share a row.
  const groups = [];
  for (const st of fuel.stations) {
    const g = groups[groups.length - 1];
    if (g && st.at_m - g[g.length - 1].at_m < 3200) g.push(st);
    else groups.push([st]);
  }
  const ol = $("gas-list");
  ol.innerHTML = "";
  for (const g of groups) {
    const names = [...new Set(g.map((s) => s.name))];
    const off = Math.min(...g.map((s) => s.off_m));
    const fill = g.some((s) => plan.fills.has(s));
    const li = document.createElement("li");
    li.innerHTML = `<span class="gas-ico">${GAS_ICON}</span>
      <span class="name">${esc(names.slice(0, 3).join(", "))}${names.length > 3 ? ` +${names.length - 3}` : ""}
        <small>${off < 200 ? "On route" : `${fmtDist(off)} off route`}${g.length === 1 && gasDetails(g[0]) ? ` · ${gasDetails(g[0])}` : ""}</small></span>
      ${fill ? `<span class="fill" title="Planned fill-up for your fuel range">Fill up</span>` : ""}
      <span class="dist">mile ${mi(g[0].at_m)}</span>`;
    li.addEventListener("click", () => {
      if (!isOn("gas")) setKinds(["gas"], true);
      map.fitBounds(L.latLngBounds(g.map((s) => [s.lat, s.lon])), { maxZoom: 15, padding: [80, 80] });
    });
    ol.appendChild(li);
  }
}

export function initFuel() {
  $("fuel-range").addEventListener("input", (e) => {
    fuelRange = +e.target.value;
    showFuelRange();
    if (state.route) renderGas(state.route);
  });
  $("fuel-range").addEventListener("change", () => store.set("fuel-range", String(fuelRange)));
  showFuelRange();
}
