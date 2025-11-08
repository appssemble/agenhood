import { describe, it, expect, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { api, ApiError } from "./client";
import { getEntries, clearLog } from "../apiLog/store";

beforeEach(() => clearLog());

describe("api client", () => {
  it("GETs JSON and returns the parsed body", async () => {
    server.use(http.get("/v1/auth/me", () => HttpResponse.json({ id: "usr_1", role: "admin" })));
    const me = await api.get<{ id: string; role: string }>("/v1/auth/me");
    expect(me.role).toBe("admin");
  });

  it("POSTs a JSON body", async () => {
    server.use(
      http.post("/v1/containers/con_1/tasks", async ({ request }) => {
        const body = (await request.json()) as { prompt: string };
        return HttpResponse.json({ task_id: "tsk_9", status: "running", started_at: "t", echoed: body.prompt });
      })
    );
    const res = await api.post<{ task_id: string; echoed: string }>("/v1/containers/con_1/tasks", { prompt: "hi" });
    expect(res).toMatchObject({ task_id: "tsk_9", echoed: "hi" });
  });

  it("throws ApiError carrying code + message + field from the envelope", async () => {
    server.use(
      http.patch("/v1/containers/con_1/config", () =>
        HttpResponse.json({ error: { code: "validation_error", message: "tool not allowed", field: "tools" } }, { status: 400 })
      )
    );
    await expect(api.patch("/v1/containers/con_1/config", {})).rejects.toMatchObject({
      code: "validation_error", field: "tools", status: 400,
    });
    await expect(api.patch("/v1/containers/con_1/config", {})).rejects.toBeInstanceOf(ApiError);
  });

  it("falls back to a generic ApiError when the body is not an envelope", async () => {
    server.use(http.get("/v1/containers", () => new HttpResponse("nope", { status: 503 })));
    await expect(api.get("/v1/containers")).rejects.toMatchObject({ code: "http_503", status: 503 });
  });
});

describe("api client logging", () => {
  it("records a successful GET with status and response body", async () => {
    server.use(http.get("/v1/models", () => HttpResponse.json({ models: [] })));
    await api.get("/v1/models");
    const [e] = getEntries();
    expect(e.method).toBe("GET");
    expect(e.path).toBe("/v1/models");
    expect(e.status).toBe(200);
    expect(e.ok).toBe(true);
    expect(e.responseBody).toEqual({ models: [] });
    expect(typeof e.durationMs).toBe("number");
  });

  it("redacts sensitive request body fields", async () => {
    server.use(http.post("/v1/auth/login", () => HttpResponse.json({ ok: true })));
    await api.post("/v1/auth/login", { email: "a@b.c", password: "hunter2" });
    const [e] = getEntries();
    expect(e.requestBody).toEqual({ email: "a@b.c", password: "***" });
    expect(e.sessionOnly).toBe(true);
  });

  it("records an error entry when the request fails", async () => {
    server.use(
      http.get("/v1/containers", () =>
        HttpResponse.json({ error: { code: "boom", message: "nope" } }, { status: 500 }),
      ),
    );
    await expect(api.get("/v1/containers")).rejects.toBeInstanceOf(ApiError);
    const [e] = getEntries();
    expect(e.status).toBe(500);
    expect(e.ok).toBe(false);
  });

  it("logs a settled error entry when the network fails", async () => {
    server.use(http.get("/v1/down", () => HttpResponse.error()));
    await expect(api.get("/v1/down")).rejects.toBeTruthy();
    const [e] = getEntries();
    expect(e.ok).toBe(false);
    expect(typeof e.error).toBe("string");
    expect(typeof e.durationMs).toBe("number");
  });

  it("settles a 204 No Content response", async () => {
    server.use(http.delete("/v1/containers/c_1", () => new HttpResponse(null, { status: 204 })));
    await api.del("/v1/containers/c_1");
    const [e] = getEntries();
    expect(e.status).toBe(204);
    expect(e.ok).toBe(true);
    expect(typeof e.durationMs).toBe("number");
  });

  it("truncates response bodies over the size cap", async () => {
    const big = "x".repeat(40000);
    server.use(http.get("/v1/big", () => HttpResponse.text(big)));
    await api.get("/v1/big");
    const [e] = getEntries();
    expect(e.responseBytes).toBe(40000);
    expect(typeof e.responseBody).toBe("string");
    expect(e.responseBody as string).toContain("too large");
  });
});
