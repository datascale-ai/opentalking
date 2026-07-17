import assert from "node:assert/strict";
import test from "node:test";

import {
  canChangeModelForAvatar,
  isDogoLight2dAvatar,
  modelForAvatarSelection,
  normalizeAvatarModelSelection,
  pickInitialAvatarForModel,
  recommendAvatarForModel,
  videoCreationCompositionForAvatar,
  videoCreationStateForAvatar,
} from "../src/light2d/avatarSelection";
import type { SelectableAvatar } from "../src/light2d/avatarSelection";

const avatars: SelectableAvatar[] = [
  { id: "dogo-light2d", model_type: "mock", is_custom: false, client_renderer: { type: "light2d", recommended_for: ["mock"] } },
  { id: "custom-mock", model_type: "mock", is_custom: true, client_renderer: null },
  { id: "anchor", model_type: "wav2lip", is_custom: false, client_renderer: null },
];

test("backend default mock selects recommended avatar without explicit storage", () => {
  assert.equal(pickInitialAvatarForModel(avatars, "mock", null)?.id, "dogo-light2d");
  assert.equal(pickInitialAvatarForModel(avatars, "mock", { id: "custom-mock", source: "explicit" })?.id, "custom-mock");
});

test("entering mock recommends Light2D while missing recommendation keeps selection", () => {
  assert.equal(recommendAvatarForModel(avatars, "mock", "anchor"), "dogo-light2d");
  assert.equal(recommendAvatarForModel(avatars.slice(1), "mock", "anchor"), "anchor");
});

test("selecting Light2D requests mock and leaving mock finds compatible avatar", () => {
  assert.equal(modelForAvatarSelection(avatars[0], "wav2lip"), "mock");
  assert.equal(recommendAvatarForModel(avatars, "wav2lip", "dogo-light2d"), "anchor");
  assert.equal(recommendAvatarForModel(avatars.slice(0, 2), "wav2lip", "dogo-light2d"), "dogo-light2d");
});

test("explicit restored DOGO overrides a non-mock default model", () => {
  const restored = pickInitialAvatarForModel(avatars, "wav2lip", {
    id: "dogo-light2d",
    source: "explicit",
  });
  assert.deepEqual(
    normalizeAvatarModelSelection(avatars, restored?.id ?? "", "wav2lip"),
    { avatarId: "dogo-light2d", model: "mock" },
  );
});

test("Persona and direct DOGO selection share model normalization", () => {
  assert.deepEqual(
    normalizeAvatarModelSelection(avatars, "dogo-light2d", "quicktalk"),
    { avatarId: "dogo-light2d", model: "mock" },
  );
  assert.equal(modelForAvatarSelection(avatars[0], "fasterliveportrait"), "mock");
});

test("Persona DOGO normalization does not depend on avatar list timing", () => {
  assert.deepEqual(
    normalizeAvatarModelSelection([], "dogo-light2d", "quicktalk"),
    { avatarId: "dogo-light2d", model: "mock" },
  );
});

test("DOGO locks realtime model changes until another avatar is selected", () => {
  assert.equal(isDogoLight2dAvatar(avatars[0]), true);
  assert.equal(canChangeModelForAvatar(avatars[0], "mock"), true);
  assert.equal(canChangeModelForAvatar(avatars[0], "wav2lip"), false);
  assert.equal(canChangeModelForAvatar(avatars[2], "wav2lip"), true);
});

test("DOGO offline state locks model and unsupported controls", () => {
  assert.deepEqual(videoCreationStateForAvatar(avatars[0], "wav2lip"), {
    model: "mock",
    modelLocked: true,
    referenceDisabled: true,
    duoDisabled: true,
    backgroundDisabled: true,
  });
  assert.deepEqual(videoCreationStateForAvatar(avatars[2], "wav2lip"), {
    model: "wav2lip",
    modelLocked: false,
    referenceDisabled: false,
    duoDisabled: false,
    backgroundDisabled: false,
  });
});

test("DOGO offline composition omits stale background without changing layout", () => {
  assert.deepEqual(
    videoCreationCompositionForAvatar(avatars[0], {
      background_id: "old-background",
      output_width: 1080,
      output_height: 1920,
      avatar_scale: 1.25,
      avatar_offset_x: 12,
    }),
    {
      output_width: 1080,
      output_height: 1920,
      avatar_scale: 1.25,
      avatar_offset_x: 12,
    },
  );
});
