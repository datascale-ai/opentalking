export const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";

export function buildApiUrl(path: string): string {
  return `${API_BASE}${path}`;
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

export async function apiDelete<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(buildApiUrl(path), { ...init, method: "DELETE" });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json() as Promise<T>;
}

export type AvatarSummary = {
  id: string;
  name: string | null;
  manifest_id?: string | null;
  model_type: string;
  width: number;
  height: number;
};

export type TTSVoiceOption = {
  id: string;
  label: string;
  provider: string;
  voice?: string | null;
  description?: string | null;
};

export type CreateSessionResponse = { session_id: string; status: string };
