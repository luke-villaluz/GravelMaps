// Node tests for the front end's pure helpers:  node --test "tests/js/*.test.mjs"
import assert from "node:assert/strict";
import { test } from "node:test";

import { haversine, planFuel, routeSlice } from "../../static/js/geo.js";
import { esc, fmtDist, fmtTime } from "../../static/js/util.js";

const MI = 1609.344;
const station = (mi) => ({ at_m: mi * MI });

test("one tank covers a short trip", () => {
  const plan = planFuel([station(50)], 120 * MI, 150 * MI);
  assert.equal(plan.fills.size, 0);
  assert.deepEqual(plan.short, []);
});

test("fills up at the farthest station in range", () => {
  const stations = [station(60), station(100), station(200)];
  const plan = planFuel(stations, 300 * MI, 150 * MI);
  assert.deepEqual([...plan.fills], [stations[1], stations[2]]);
  assert.deepEqual(plan.short, []);
});

test("flags a stretch longer than the range", () => {
  const stations = [station(50)];
  const plan = planFuel(stations, 300 * MI, 100 * MI);
  assert.deepEqual([...plan.fills], [stations[0]]);
  assert.equal(plan.short.length, 1);
  assert.equal(plan.short[0].from_m, 50 * MI);
  assert.equal(plan.short[0].to_m, 300 * MI);
});

test("haversine: one degree of longitude at the equator", () => {
  assert.ok(Math.abs(haversine(0, 0, 0, 1) - 111195) < 1);
});

test("routeSlice cuts the route between two distances", () => {
  const route = { features: [{ geometry: { coordinates: [[0, 0], [1, 0]] } }] };
  const half = haversine(0, 0, 0, 1) / 2;
  const [a, b] = routeSlice(route, 0, half);
  assert.deepEqual(a, [0, 0]);
  assert.ok(Math.abs(b[1] - 0.5) < 1e-9 && b[0] === 0);
});

test("formatting", () => {
  assert.equal(fmtDist(50), "164 ft");
  assert.equal(fmtDist(5.24 * MI), "5.2 mi");
  assert.equal(fmtDist(42.4 * MI), "42 mi");
  assert.equal(fmtTime(600), "10 min");
  assert.equal(fmtTime(3725), "1 hr 2 min");
  assert.equal(esc('<a href="x">&'), "&lt;a href=&quot;x&quot;&gt;&amp;");
});
