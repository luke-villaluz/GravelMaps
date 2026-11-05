// App state: stops, per-leg styles and vehicles, the current route, and the server's /api/region info.

import { store } from "./util.js";

// Display info per road kind; keys match the server's KINDS. Order = legend order.
export const KINDS = {
  unpaved: { label: "Dirt / Gravel", color: "--k-unpaved" },
  rough: { label: "Rough / 4x4", color: "--k-rough", dash: "6 5" },
  trail: { label: "Singletrack / OHV", color: "--k-trail", dash: "2 6" },
  unknown: { label: "Surface Unknown", color: "--k-unknown" },
  paved: { label: "Paved", color: "--k-paved" },
  major: { label: "Major Road", color: "--k-major" },
  highway: { label: "Highway", color: "--k-highway" },
};

export const state = {
  stops: [null, null], // each: {lat, lon, label} or null
  legs: [], // slider values per leg (arrays in server kind order)
  vehicles: ["car"], // vehicle per leg, e.g. drive the car in, then ride the bike
  activeLeg: 0,
  route: null,
  basemap: store.get("ui.basemap") || "satellite",
  info: null, // /api/region: profiles, kinds, presets
};

export const stopRole = (i) => (i === 0 ? "start" : i === state.stops.length - 1 ? "end" : "via");
export const stopLetter = (i) => (i === 0 ? "A" : i === state.stops.length - 1 ? "B" : String(i));

// ---------- legs (per-leg route style) ----------
export const kindKeys = () => state.info.kinds.map((k) => k.key);
export const presetValues = (key) => [...state.info.presets[key].values];
export const defaultLeg = () => presetValues(state.info.default_preset);
export const presetFits = (key, vehicle) => !state.info.presets[key].vehicles || state.info.presets[key].vehicles.includes(vehicle);
export const presetOf = (values) =>
  Object.keys(state.info.presets).find((k) => state.info.presets[k].values.every((v, i) => v === values[i])) || null;

export function syncLegs() {
  const n = Math.max(1, state.stops.length - 1);
  while (state.legs.length < n) state.legs.push([...(state.legs[state.legs.length - 1] || defaultLeg())]);
  state.legs.length = n;
  while (state.vehicles.length < n) state.vehicles.push(state.vehicles[state.vehicles.length - 1] || "car");
  state.vehicles.length = n;
  state.activeLeg = Math.min(state.activeLeg, n - 1);
}

export function insertStop(i, stop) {
  // A new stop splits leg i-1 in two; both halves keep its style.
  state.stops.splice(i, 0, stop);
  state.legs.splice(i - 1, 0, [...state.legs[i - 1]]);
  state.vehicles.splice(i - 1, 0, state.vehicles[i - 1]);
}
