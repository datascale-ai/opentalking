export type ModelStatus = {
  id: string;
  backend?: string;
  connected: boolean;
  reason?: string;
};

export type ModelConnectionBadge = {
  connected: boolean;
  label: string;
  tone: "connected" | "disconnected" | "selfTest";
};

export function isSelfTestModel(status?: ModelStatus | null): boolean {
  return status?.id === "mock" || status?.reason === "local_self_test";
}

export function modelConnectionBadge(
  status: ModelStatus | undefined,
  fallbackConnected = false,
): ModelConnectionBadge {
  if (isSelfTestModel(status)) {
    return { connected: true, label: "无需连接", tone: "selfTest" };
  }
  const connected = status?.connected ?? fallbackConnected;
  return {
    connected,
    label: connected ? "已连接" : "未连接",
    tone: connected ? "connected" : "disconnected",
  };
}
