import assert from "node:assert/strict";
import test from "node:test";

import { modelLabel } from "../src/lib/modelLabels";

test("shared model labels hide the internal mock identifier", () => {
  assert.equal(modelLabel("mock"), "轻量模式");
  assert.equal(modelLabel("wav2lip"), "Wav2Lip");
  assert.equal(modelLabel("future-model"), "future-model");
});
