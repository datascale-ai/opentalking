export const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";

export function buildApiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

/** 与当前页同源的 WebSocket（经 Vite 代理到后端时需开启 proxy.ws） */
export function buildWsUrl(path: string): string {
  const proto = typeof window !== "undefined" && window.location.protocol === "https:" ? "wss:" : "ws:";
  const host = typeof window !== "undefined" ? window.location.host : "127.0.0.1:5173";
  const p = path.startsWith("/") ? path : `/${path}`;
  return `${proto}//${host}${API_BASE}${p}`;
}

export async function apiGet<T>(path: string): Promise<T> {
  const r = await fetch(buildApiUrl(path));
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json() as Promise<T>;
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(buildApiUrl(path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json() as Promise<T>;
}

/** multipart/form-data（语音识别 speak_audio / transcribe） */
export async function apiPostForm<T>(path: string, form: FormData, init?: RequestInit): Promise<T> {
  const r = await fetch(buildApiUrl(path), { method: "POST", body: form, ...init });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json() as Promise<T>;
}

export async function apiDelete<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(buildApiUrl(path), { ...init, method: "DELETE" });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json() as Promise<T>;
}

export type AvatarSummary = {
  id: string;
  name: string | null;
  model_type: string;
  width: number;
  height: number;
};

export type CreateSessionResponse = { session_id: string; status: string };

/** GET /voices 返回的音色目录项（含 SQLite 中的系统预设与复刻） */
export type VoiceCatalogItem = {
  id: number;
  user_id: number;
  provider: string;
  voice_id: string;
  display_label: string;
  target_model: string | null;
  source: "system" | "clone" | string;
};
