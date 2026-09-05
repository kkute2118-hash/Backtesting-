import type { ApiErrorBody } from "@/types/api";

const BASE = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
const PREFIX = "/api/v1";

/**
 * A failure the UI can actually show someone.
 *
 * The backend answers every error with one envelope, so the message on this
 * class is always something written for a person ("Dhan is not configured...")
 * rather than a stack trace. `code` lets a component react to the *kind* of
 * failure — an unconfigured provider gets a "set this up" panel, a 404 gets an
 * empty state — without string-matching the message.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail?: string;

  constructor(status: number, code: string, message: string, detail?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
  }

  get isNotConfigured() {
    return this.code === "not_configured";
  }
  get isNotFound() {
    return this.status === 404;
  }
}

const NETWORK_MESSAGE =
  "Cannot reach the analysis server. Check that the backend is running and that " +
  "NEXT_PUBLIC_API_URL points at it.";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${PREFIX}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {}),
      },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "network_error", NETWORK_MESSAGE);
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = null;
    }
  }

  if (!response.ok) {
    const envelope = body as ApiErrorBody | null;
    if (envelope?.error?.message) {
      throw new ApiError(response.status, envelope.error.code, envelope.error.message,
        envelope.error.detail);
    }
    // FastAPI's own validation errors come back under `detail`.
    const detail = (body as { detail?: unknown } | null)?.detail;
    if (Array.isArray(detail) && detail.length) {
      const first = detail[0] as { msg?: string; loc?: unknown[] };
      const field = Array.isArray(first.loc) ? first.loc.slice(1).join(".") : "";
      throw new ApiError(response.status, "invalid_request",
        field ? `${field}: ${first.msg ?? "is invalid"}` : (first.msg ?? "Invalid request"));
    }
    throw new ApiError(response.status, "error",
      typeof detail === "string" ? detail : `Request failed (${response.status}).`);
  }

  return body as T;
}

function query(params: Record<string, unknown> | undefined): string {
  if (!params) return "";
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) {
      value.forEach((entry) => search.append(key, String(entry)));
    } else {
      search.set(key, String(value));
    }
  }
  const serialised = search.toString();
  return serialised ? `?${serialised}` : "";
}

export const api = {
  get: <T>(path: string, params?: Record<string, unknown>) =>
    request<T>(`${path}${query(params)}`),
  post: <T>(path: string, body?: unknown, params?: Record<string, unknown>) =>
    request<T>(`${path}${query(params)}`, {
      method: "POST",
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}
