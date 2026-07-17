import assert from "node:assert/strict";
import test from "node:test";

import { parseLight2dConfig } from "../src/light2d/config";

function validConfig() {
  const layer = (source: string) => ({ source, rect: [0, 0, 1, 1] });
  return {
    version: 1,
    canvas: { width: 1, height: 1 },
    layers: {
      base: layer("base.png"),
      blink: layer("blink.png"),
      mouth: {
        closed: layer("closed.png"),
        small: layer("small.png"),
        medium: layer("medium.png"),
        large: layer("large.png"),
      },
    },
    audio: {
      silence_gate: 0.025,
      small_threshold: 0.055,
      medium_threshold: 0.105,
      attack_ms: 45,
      release_ms: 120,
      crossfade_ms: 80,
    },
    animation: {
      breath_period_ms: 2600,
      breath_scale: 0.006,
      sway_degrees: 0.7,
      blink_period_ms: 4800,
      blink_duration_ms: 130,
    },
  };
}

test("Light2D version 1 rejects fractional layer rectangles", () => {
  const config = validConfig();
  config.layers.base.rect = [0.5, 0, 0.5, 1];

  assert.throws(() => parseLight2dConfig(config), /invalid Light2D layers/);
});
