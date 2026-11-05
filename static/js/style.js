// Route Style panel: vehicle tabs, leg tabs, presets and sliders.

import { $, esc, fmtDist, fmtTimeShort, store } from "./util.js";
import { defaultLeg, kindKeys, KINDS, presetFits, presetOf, presetValues, state, stopLetter } from "./state.js";
import { PEAK_ICON, PROFILE_ICONS } from "./icons.js";
import { renderRoute } from "./route.js";
import { update } from "./main.js";

function sliderWord(v) {
  if (v === 0) return "Never";
  if (v <= 25) return "Avoid";
  if (v <= 45) return "Less";
  if (v <= 55) return "Neutral";
  if (v <= 75) return "More";
  return "Prefer";
}

export function renderStyle() {
  const legs = state.legs;
  const multi = legs.length > 1;
  const active = legs[state.activeLeg];

  const tabs = $("legs");
  tabs.hidden = !multi;
  $("apply-all").hidden = !multi;
  tabs.innerHTML = "";
  if (multi) {
    legs.forEach((v, i) => {
      const b = document.createElement("button");
      b.classList.toggle("on", i === state.activeLeg);
      const leg = state.route?.legs?.[i];
      const preset = presetOf(v);
      const sub = leg ? `${fmtDist(leg.distance_m)} · ${fmtTimeShort(leg.duration_s)}` : (preset ? state.info.presets[preset].label : "Custom");
      b.innerHTML = `<b>${PROFILE_ICONS[state.vehicles[i]] || ""}${stopLetter(i)} → ${stopLetter(i + 1)}</b><small>${esc(sub)}</small>`;
      b.addEventListener("click", () => { state.activeLeg = i; renderProfiles(); renderStyle(); renderRoute(); });
      tabs.appendChild(b);
    });
  }

  const chips = $("presets");
  chips.innerHTML = "";
  const current = presetOf(active);
  for (const [key, p] of Object.entries(state.info.presets)) {
    if (!presetFits(key, state.vehicles[state.activeLeg])) continue;
    const b = document.createElement("button");
    b.textContent = p.label;
    b.classList.toggle("on", key === current);
    b.addEventListener("click", () => {
      state.legs[state.activeLeg] = presetValues(key);
      update();
    });
    chips.appendChild(b);
  }
  if (!current) {
    const b = document.createElement("button");
    b.textContent = "Custom";
    b.className = "on custom";
    chips.appendChild(b);
  }

  const box = $("sliders");
  box.innerHTML = "";
  const allowed = state.info.profiles[state.vehicles[state.activeLeg]].kinds;
  kindKeys().forEach((key, idx) => {
    if (!allowed.includes(key)) return;
    const k = KINDS[key];
    const v = active[idx];
    const row = document.createElement("div");
    row.className = "slider-row";
    row.innerHTML = `
      <div class="top"><i style="background:var(${k.color})"></i><span>${k.label}</span><em></em></div>
      <input type="range" min="0" max="100" step="1" aria-label="${k.label}">`;
    const input = row.querySelector("input");
    const word = row.querySelector("em");
    const show = (val) => {
      input.style.setProperty("--pct", `${val}%`);
      word.textContent = sliderWord(val);
      word.classList.toggle("never", val === 0);
    };
    input.value = v;
    input.style.setProperty("--c", `var(${k.color})`);
    show(v);
    input.addEventListener("input", () => show(+input.value));
    input.addEventListener("change", () => {
      state.legs[state.activeLeg][idx] = +input.value;
      update();
    });
    box.appendChild(row);
  });

  // High Elevation: same scale, but about how high up a road is rather than what it's made of.
  if (state.info.elevation?.ready) {
    const idx = kindKeys().length;
    const row = document.createElement("div");
    row.className = "slider-row elev";
    row.innerHTML = `
      <div class="top">${PEAK_ICON}<span>${esc(state.info.elevation.label)}</span><em></em></div>
      <input type="range" min="0" max="100" step="1" aria-label="${esc(state.info.elevation.label)}">
      <small>Ridges, passes and summit roads, over the valley floors.</small>`;
    const input = row.querySelector("input");
    const word = row.querySelector("em");
    const show = (val) => {
      input.style.setProperty("--pct", `${val}%`);
      word.textContent = val <= 25 ? "Stay low" : val <= 45 ? "Less" : val <= 55 ? "Neutral" : val <= 75 ? "More" : "Seek";
    };
    input.value = active[idx];
    input.style.setProperty("--c", "var(--k-elev)");
    show(active[idx]);
    input.addEventListener("input", () => show(+input.value));
    input.addEventListener("change", () => {
      state.legs[state.activeLeg][idx] = +input.value;
      update();
    });
    box.appendChild(row);
  }
}

export function renderProfiles() {
  const box = $("profiles");
  box.innerHTML = "";
  for (const [key, p] of Object.entries(state.info.profiles)) {
    const b = document.createElement("button");
    b.innerHTML = `${PROFILE_ICONS[key] || ""}<span>${esc(p.label)}</span>`;
    b.setAttribute("role", "tab");
    b.classList.toggle("on", key === state.vehicles[state.activeLeg]);
    b.addEventListener("click", () => {
      if (state.vehicles[state.activeLeg] === key) return;
      state.vehicles[state.activeLeg] = key;
      // A bike-only style (e.g. Singletrack / OHV) makes no sense for the car; fall back to the default.
      const preset = presetOf(state.legs[state.activeLeg]);
      if (preset && !presetFits(preset, key)) state.legs[state.activeLeg] = defaultLeg();
      update();
    });
    box.appendChild(b);
  }
  // With several legs these tabs set the vehicle for the leg being edited.
  const note = $("mode-note");
  note.hidden = state.legs.length < 2;
  note.textContent = `Vehicle for ${stopLetter(state.activeLeg)} → ${stopLetter(state.activeLeg + 1)} · pick a leg under Route Style`;
}

const customizeOpen = () => $("customize").getAttribute("aria-expanded") === "true";
function setCustomize(open) {
  $("customize").setAttribute("aria-expanded", String(open));
  $("sliders").hidden = !open;
  store.set("customize", open ? "1" : "0");
}

export function initStyle() {
  $("apply-all").addEventListener("click", () => {
    const v = state.legs[state.activeLeg];
    state.legs = state.legs.map(() => [...v]);
    update();
  });
  $("customize").addEventListener("click", () => setCustomize(!customizeOpen()));
  setCustomize(store.get("customize") === "1");
}
