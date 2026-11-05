// The route kept in the URL, so it can be bookmarked or shared.

import { fmtLL } from "./util.js";
import { defaultLeg, kindKeys, presetOf, presetValues, state } from "./state.js";

// #pts=lat,lon;lat,lon&v=car,dualsport&l=mostly,dirt   (per leg: a vehicle, and a preset key or 7 dot-separated values)
export function writeHash() {
  const p = new URLSearchParams();
  const pts = state.stops.filter(Boolean);
  if (pts.length) p.set("pts", pts.map((s) => `${s.lat.toFixed(5)},${s.lon.toFixed(5)}`).join(";"));
  p.set("v", state.vehicles.join(","));
  p.set("l", state.legs.map((v) => presetOf(v) || v.join(".")).join(","));
  history.replaceState(null, "", `#${p}`);
}

export function readHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  const vehicles = (p.get("v") || "").split(",").filter((v) => state.info.profiles[v]);
  if (vehicles.length) state.vehicles = vehicles;
  const pts = (p.get("pts") || "").split(";").filter(Boolean).map((t) => {
    const [lat, lon] = t.split(",").map(Number);
    return { lat, lon, label: fmtLL(lat, lon) };
  });
  if (pts.length === 1) pts.push(null);
  if (pts.length >= 2) state.stops = pts;
  const n = kindKeys().length + 1; // road kinds, then High Elevation
  state.legs = (p.get("l") || "").split(",").filter(Boolean).map((t) => {
    if (state.info.presets[t]) return presetValues(t);
    const v = t.split(".").map(Number);
    if (v.length === n - 1) v.push(50); // links from before the elevation slider
    return v.length === n && v.every((x) => x >= 0 && x <= 100) ? v : defaultLeg();
  });
}
