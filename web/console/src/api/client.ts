import type { ApiErrorBody } from "./types";
import { logStart, logEnd } from "../apiLog/store";
import { redact } from "../apiLog/redact";
import { isSessionOnly } from "../apiLog/curl";
import { API_BASE as BASE } from "./base";

const MAX_BODY = 32 * 1024;

export class ApiError extends Error {
  constructor(public code: string, message: string, public status: number, public field?: string) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let logId = "";
  try {
    logId = logStart({
      kind: "rest",
      method,
      path,
      requestBody: body !== undefined ? redact(body) : undefined,
      sessionOnly: isSessionOnly(path),
    });
  } catch {
    /* logging must never break a request */
  }

  let res: Response;
  try {
    res = await fetch(BASE + path, {
      method,
      credentials: "include", // same-origin HttpOnly session cookie
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (err) {
    logEnd(logId, { ok: false, error: err instanceof Error ? err.message : String(err) });
    throw err;
  }

  if (res.status === 204) {
    logEnd(logId, { status: 204, ok: true });
    return undefined as T;
  }

  let text: string;
  try {
    text = await res.text();
  } catch (err) {
    logEnd(logId, { ok: false, error: err instanceof Error ? err.message : String(err) });
    throw err;
  }
  let parsed: unknown = undefined;
  try { parsed = text ? JSON.parse(text) : undefined; } catch { /* not JSON */ }

  logEnd(logId, {
    status: res.status,
    ok: res.ok,
    responseBytes: text.length,
    responseBody:
      text.length > MAX_BODY
        ? `(response too large to capture: ${text.length} bytes)`
        : redact(parsed),
  });

  if (!res.ok) {
    const envelope = parsed as ApiErrorBody | undefined;
    if (envelope?.error?.code) {
      throw new ApiError(envelope.error.code, envelope.error.message, res.status, envelope.error.field);
    }
    throw new ApiError(`http_${res.status}`, text || res.statusText, res.status);
  }
  return parsed as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body),
  del: <T>(path: string, body?: unknown) => request<T>("DELETE", path, body),
};
