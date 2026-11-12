import { test } from "node:test";
import assert from "node:assert/strict";
import { shownBasemap } from "../../static/js/online.js";

const maps = (offlineMap) => ({
  map: { needsNet: () => !offlineMap },
  satellite: { needsNet: () => true },
  topo: { needsNet: () => true },
});

test("online: the chosen basemap", () => {
  assert.equal(shownBasemap("satellite", maps(true), true), "satellite");
});

test("offline: falls back to the downloaded map", () => {
  assert.equal(shownBasemap("satellite", maps(true), false), "map");
  assert.equal(shownBasemap("map", maps(true), false), "map");
});

test("offline with nothing downloaded: keeps the choice", () => {
  assert.equal(shownBasemap("topo", maps(false), false), "topo");
});
