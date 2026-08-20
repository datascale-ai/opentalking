import assert from "node:assert/strict";
import test from "node:test";

import {
  RUNTIME_LLM_DEFAULT,
  RUNTIME_LLM_PRESETS,
  normalizeRuntimeLlmProvider,
} from "../src/lib/llmPresets";

test("llm presets include the named OrcaRouter gateway", () => {
  assert.ok("orcarouter" in RUNTIME_LLM_PRESETS);
  assert.equal(RUNTIME_LLM_PRESETS.orcarouter.baseUrl, "https://api.orcarouter.ai/v1");
  assert.equal(RUNTIME_LLM_PRESETS.orcarouter.model, "orcarouter/auto");
  assert.equal(RUNTIME_LLM_PRESETS.orcarouter.label, "OrcaRouter");
});

test("llm default preset is DashScope", () => {
  assert.equal(RUNTIME_LLM_DEFAULT, RUNTIME_LLM_PRESETS.dashscope);
});

test("normalizeRuntimeLlmProvider resolves known providers and falls back to dashscope", () => {
  assert.equal(normalizeRuntimeLlmProvider("orcarouter"), "orcarouter");
  assert.equal(normalizeRuntimeLlmProvider("openai_compatible"), "openai_compatible");
  assert.equal(normalizeRuntimeLlmProvider("dashscope"), "dashscope");
  assert.equal(normalizeRuntimeLlmProvider("unknown-provider"), "dashscope");
  assert.equal(normalizeRuntimeLlmProvider(null), "dashscope");
});
