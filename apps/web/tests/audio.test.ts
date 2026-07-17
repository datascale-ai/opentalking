import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { computeRms, createEnergySmoother, mouthStateForEnergy } from "../src/light2d/audio";

type AudioFixture = {
  thresholds: Parameters<typeof mouthStateForEnergy>[1];
  cases: Array<{
    name: string;
    normalized_samples: number[];
    expected_rms: number;
    expected_mouth_state: ReturnType<typeof mouthStateForEnergy>;
  }>;
};

const fixture = JSON.parse(
  readFileSync(new URL("../../../tests/fixtures/light2d_audio_cases.json", import.meta.url), "utf8"),
) as AudioFixture;

test("computeRms measures normalized time-domain samples", () => {
  assert.equal(computeRms(new Float32Array([0.5, -0.5])), 0.5);
});

test("shared audio fixture matches browser RMS and mouth states", () => {
  for (const fixtureCase of fixture.cases) {
    const rms = computeRms(new Float32Array(fixtureCase.normalized_samples));
    assert.ok(Math.abs(rms - fixtureCase.expected_rms) < 1e-7, fixtureCase.name);
    assert.equal(mouthStateForEnergy(rms, fixture.thresholds), fixtureCase.expected_mouth_state);
  }
});

test("mouth thresholds use inclusive lower bounds", () => {
  const config = { silence_gate: 0.03, small_threshold: 0.08, medium_threshold: 0.18 };
  assert.equal(mouthStateForEnergy(0.029, config), "closed");
  assert.equal(mouthStateForEnergy(0.03, config), "small");
  assert.equal(mouthStateForEnergy(0.08, config), "medium");
  assert.equal(mouthStateForEnergy(0.18, config), "large");
});

test("energy smoother attacks faster than it releases", () => {
  const smoother = createEnergySmoother({ attack_ms: 40, release_ms: 160 });
  const attacked = smoother.update(1, 20);
  const released = smoother.update(0, 20);
  assert.ok(attacked > 0.3);
  assert.ok(released > 0);
  assert.ok(attacked - released < attacked);
});
