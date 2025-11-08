export type ApiLogKind = "rest" | "sse";

export interface ApiLogEntry {
  id: string;
  kind: ApiLogKind;
  method: string; // "GET" | "POST" | ... | "SSE"
  path: string; // e.g. /v1/containers/c_8a/tasks
  startedAt: number; // epoch ms
  durationMs?: number;
  status?: number;
  ok?: boolean;
  requestBody?: unknown; // redacted, cloned
  responseBody?: unknown; // redacted, cloned, size-capped
  responseBytes?: number; // approximate size: text length in UTF-16 code units
  error?: string;
  sessionOnly?: boolean;
  sse?: { events: number; closed: boolean };
}
