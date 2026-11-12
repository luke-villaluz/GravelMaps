import { test } from "node:test";
import assert from "node:assert/strict";
import { dropIndex, moveStop, state } from "../../static/js/state.js";

test("dropIndex counts the rows whose middle is above", () => {
  assert.equal(dropIndex(10, [28, 84]), 0);
  assert.equal(dropIndex(60, [28, 84]), 1);
  assert.equal(dropIndex(200, [28, 84]), 2);
  assert.equal(dropIndex(84, [28, 84]), 2); // dragged all the way down: clamped onto the last row
});

test("moveStop reorders stops", () => {
  state.stops = ["A", "B", "C", "D"];
  assert.equal(moveStop(0, 2), true);
  assert.deepEqual(state.stops, ["B", "C", "A", "D"]);
  assert.equal(moveStop(3, 0), true);
  assert.deepEqual(state.stops, ["D", "B", "C", "A"]);
  assert.equal(moveStop(1, 1), false);
});
