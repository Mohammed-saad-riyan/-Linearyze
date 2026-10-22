import type { Me, PassageView, Receipt } from "./types";

async function sha256Hex(bytes: ArrayBuffer): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public body: unknown,
  ) {
    super(`HTTP ${status}`);
  }
}

/** POST JSON and keep the exact bytes, so the debug strip can hash what arrived. */
export async function postMeasured<T>(path: string, body: unknown): Promise<{ data: T; receipt: Receipt }> {
  const started = performance.now();
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    credentials: "same-origin",
  });
  const bytes = await response.arrayBuffer();
  const ms = performance.now() - started;
  const text = new TextDecoder().decode(bytes);
  const data = text ? JSON.parse(text) : null;
  if (response.status === 401) throw new ApiError(401, data);
  // 413 (M5), 429 (M6), 503 (M3) and 504 (M4) carry a defined message body: render it.
  if (!response.ok && !(data && typeof data === "object" && "message_id" in data)) {
    throw new ApiError(response.status, data);
  }
  return {
    data: data as T,
    receipt: { status: response.status, bytes: bytes.byteLength, sha256: await sha256Hex(bytes), ms },
  };
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { credentials: "same-origin" });
  if (!response.ok) throw new ApiError(response.status, await response.json().catch(() => null));
  return response.json() as Promise<T>;
}

export const api = {
  me: () => getJson<Me>("/api/auth/me"),
  login: async (email: string, password: string) => {
    const response = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    if (!response.ok) throw new ApiError(response.status, null);
  },
  logout: () => fetch("/api/auth/logout", { method: "POST" }),
  messages: () => getJson<Record<string, { en: string; ar: string }>>("/api/messages"),
  passage: (documentId: string, chunkId: number) =>
    getJson<PassageView>(`/api/documents/${encodeURIComponent(documentId)}/passages/${chunkId}`),
  users: () =>
    getJson<{ email: string; name: string; role: string; active: boolean; events: string[] }[]>(
      "/api/admin/users",
    ),
  downloadUrl: (documentId: string) => `/api/documents/${encodeURIComponent(documentId)}/download`,
};
