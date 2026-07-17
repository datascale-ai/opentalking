export type ClientRendererSummary = {
  type: "light2d";
  recommended_for: string[];
};

export type SelectableAvatar = {
  id: string;
  model_type: string;
  is_custom: boolean;
  client_renderer: ClientRendererSummary | null;
};

export type StoredAvatarChoice = { id: string; source: string | null };

export const DOGO_LIGHT2D_AVATAR_ID = "dogo-light2d";

export function isDogoLight2dAvatar(
  avatar: SelectableAvatar | null | undefined,
): boolean {
  return avatar?.id === DOGO_LIGHT2D_AVATAR_ID;
}

function recommendedAvatar<T extends SelectableAvatar>(avatars: T[], model: string): T | null {
  return avatars.find(
    (avatar) => !avatar.is_custom && avatar.client_renderer?.recommended_for.includes(model),
  ) ?? null;
}

export function pickInitialAvatarForModel<T extends SelectableAvatar>(
  avatars: T[],
  model: string,
  stored: StoredAvatarChoice | null,
): T | null {
  const storedAvatar = stored ? avatars.find((avatar) => avatar.id === stored.id) ?? null : null;
  if (storedAvatar && (stored?.source === "explicit" || storedAvatar.is_custom)) return storedAvatar;
  return recommendedAvatar(avatars, model) ?? storedAvatar ?? avatars[0] ?? null;
}

export function recommendAvatarForModel<T extends SelectableAvatar>(
  avatars: T[],
  model: string,
  currentAvatarId: string,
): string {
  if (model === "mock") return recommendedAvatar(avatars, model)?.id ?? currentAvatarId;
  const current = avatars.find((avatar) => avatar.id === currentAvatarId);
  if (current?.client_renderer?.type === "light2d") {
    return avatars.find((avatar) => avatar.model_type === model)?.id ?? currentAvatarId;
  }
  return currentAvatarId;
}

export function modelForAvatarSelection(
  avatar: SelectableAvatar | undefined,
  currentModel: string,
): string {
  return avatar?.client_renderer?.type === "light2d" ? "mock" : currentModel;
}

export function normalizeAvatarModelSelection<T extends SelectableAvatar>(
  avatars: T[],
  avatarId: string,
  requestedModel: string,
): { avatarId: string; model: string } {
  const avatar = avatars.find((item) => item.id === avatarId);
  return {
    avatarId,
    model: avatarId === DOGO_LIGHT2D_AVATAR_ID
      ? "mock"
      : modelForAvatarSelection(avatar, requestedModel),
  };
}

export function canChangeModelForAvatar(
  avatar: SelectableAvatar | null | undefined,
  nextModel: string,
): boolean {
  return !isDogoLight2dAvatar(avatar) || nextModel === "mock";
}

export type VideoCreationAvatarState = {
  model: string;
  modelLocked: boolean;
  referenceDisabled: boolean;
  duoDisabled: boolean;
  backgroundDisabled: boolean;
};

export function videoCreationStateForAvatar(
  avatar: SelectableAvatar | null | undefined,
  requestedModel: string,
): VideoCreationAvatarState {
  const locked = isDogoLight2dAvatar(avatar);
  return {
    model: locked ? "mock" : requestedModel,
    modelLocked: locked,
    referenceDisabled: locked,
    duoDisabled: locked,
    backgroundDisabled: locked,
  };
}

export function videoCreationCompositionForAvatar<
  T extends { background_id?: string | null },
>(avatar: SelectableAvatar | null | undefined, composition: T): Omit<T, "background_id"> | T {
  if (!isDogoLight2dAvatar(avatar)) return composition;
  const { background_id: _backgroundId, ...withoutBackground } = composition;
  return withoutBackground;
}
