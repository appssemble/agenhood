import { describe, it, expect } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import type { ReactNode } from "react";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import {
  useSelectTenant, useAllTenants, useCreateTenant, useTasks, useSessions, useTaskPages, fetchAllTaskEvents,
} from "./queries";

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  );
}

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient();
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("useSelectTenant", () => {
  it("POSTs the chosen tenant_id to /v1/auth/select-tenant", async () => {
    let received: unknown = null;
    server.use(http.post("/v1/auth/select-tenant", async ({ request }) => {
      received = await request.json();
      return HttpResponse.json({ active_tenant_id: "ten_b", role: "member" });
    }));
    const { result } = renderHook(() => useSelectTenant(), { wrapper: wrap() });
    await result.current.mutateAsync("ten_b");
    expect(received).toEqual({ tenant_id: "ten_b" });
  });

  it("sends tenant_id null for staff exit", async () => {
    let received: unknown = null;
    server.use(http.post("/v1/auth/select-tenant", async ({ request }) => {
      received = await request.json();
      return HttpResponse.json({ active_tenant_id: null, role: null });
    }));
    const { result } = renderHook(() => useSelectTenant(), { wrapper: wrap() });
    await result.current.mutateAsync(null);
    expect(received).toEqual({ tenant_id: null });
  });
});

describe("useAllTenants", () => {
  it("is disabled when enabled=false (does not fetch)", async () => {
    const { result } = renderHook(() => useAllTenants(false), { wrapper: wrap() });
    expect(result.current.fetchStatus).toBe("idle");
  });

  it("fetches /admin/v1/tenants when enabled", async () => {
    server.use(http.get("/admin/v1/tenants", () =>
      HttpResponse.json({ tenants: [{ id: "ten_a", name: "Acme" }] })));
    const { result } = renderHook(() => useAllTenants(true), { wrapper: wrap() });
    await waitFor(() => expect(result.current.data?.tenants?.[0]?.name).toBe("Acme"));
  });
});

describe("useCreateTenant", () => {
  it("POSTs { name } to /v1/tenants", async () => {
    let received: unknown = null;
    server.use(http.post("/v1/tenants", async ({ request }) => {
      received = await request.json();
      return HttpResponse.json({ id: "ten_new", name: "Acme", owner_id: "usr_s" });
    }));
    const { result } = renderHook(() => useCreateTenant(), { wrapper: wrap() });
    const res = await result.current.mutateAsync("Acme");
    expect(received).toEqual({ name: "Acme" });
    expect(res.id).toBe("ten_new");
  });
});

describe("useTasks session_id filter", () => {
  it("omits the query param when no sessionId is given", async () => {
    let seenUrl = "";
    server.use(http.get("/v1/containers/con_1/tasks", ({ request }) => {
      seenUrl = request.url;
      return HttpResponse.json({ tasks: [] });
    }));
    const { result } = renderHook(() => useTasks("con_1"), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(seenUrl).not.toContain("session_id");
  });

  it("includes session_id when given", async () => {
    let seenUrl = "";
    server.use(http.get("/v1/containers/con_1/tasks", ({ request }) => {
      seenUrl = request.url;
      return HttpResponse.json({ tasks: [] });
    }));
    const { result } = renderHook(() => useTasks("con_1", "sess-1"), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(seenUrl).toContain("session_id=sess-1");
  });
});

describe("useSessions", () => {
  it("fetches the sessions list for a container", async () => {
    server.use(http.get("/v1/containers/con_1/sessions", () => HttpResponse.json({
      sessions: [{ session_id: "sess-1", driver: "vanilla", task_count: 2,
        first_created_at: "t1", last_created_at: "t2", busy: false }],
    })));
    const { result } = renderHook(() => useSessions("con_1"), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.sessions[0].session_id).toBe("sess-1");
  });
});

describe("useSessions pagination", () => {
  it("asks for a page and appends the next one on fetchNextPage", async () => {
    const seen: (string | null)[] = [];
    server.use(http.get("/v1/containers/con_1/sessions", ({ request }) => {
      const url = new URL(request.url);
      seen.push(url.searchParams.get("cursor"));
      expect(url.searchParams.get("limit")).toBe("50");
      const row = (id: string) => ({ session_id: id, driver: "vanilla", task_count: 1,
        first_created_at: "t1", last_created_at: "t2", busy: false });
      return url.searchParams.get("cursor") === "c1"
        ? HttpResponse.json({ sessions: [row("sess-2")], next_cursor: null })
        : HttpResponse.json({ sessions: [row("sess-1")], next_cursor: "c1" });
    }));
    const { result } = renderHook(() => useSessions("con_1"), { wrapper });
    await waitFor(() => expect(result.current.hasNextPage).toBe(true));
    await result.current.fetchNextPage();
    await waitFor(() => expect(result.current.data?.sessions.map((s) => s.session_id)).toEqual(["sess-1", "sess-2"]));
    expect(result.current.hasNextPage).toBe(false);
    expect(seen).toEqual([null, "c1"]);
  });
});

describe("useTaskPages", () => {
  const task = (id: string) => ({ task_id: id, status: "completed", prompt: id });

  it("sends the session filter with the cursor and flattens pages", async () => {
    server.use(http.get("/v1/containers/con_1/tasks", ({ request }) => {
      const url = new URL(request.url);
      expect(url.searchParams.get("session_id")).toBe("sess-1");
      return url.searchParams.get("cursor") === "c1"
        ? HttpResponse.json({ tasks: [task("tsk_old")], next_cursor: null })
        : HttpResponse.json({ tasks: [task("tsk_new")], next_cursor: "c1" });
    }));
    const { result } = renderHook(() => useTaskPages("con_1", "sess-1"), { wrapper });
    await waitFor(() => expect(result.current.hasNextPage).toBe(true));
    await result.current.fetchNextPage();
    await waitFor(() => expect(result.current.data?.tasks.map((t) => t.task_id)).toEqual(["tsk_new", "tsk_old"]));
  });

  it("treats a response without next_cursor as the last page", async () => {
    server.use(http.get("/v1/containers/con_1/tasks", () => HttpResponse.json({ tasks: [task("tsk_1")] })));
    const { result } = renderHook(() => useTaskPages("con_1"), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.hasNextPage).toBe(false);
  });
});

describe("fetchAllTaskEvents", () => {
  const ev = (seq: number) => ({ seq, type: "log", ts: "t", payload: {} });

  it("follows next_after_seq until the last page", async () => {
    const asked: (string | null)[] = [];
    server.use(http.get("/v1/containers/con_1/tasks/tsk_1/events", ({ request }) => {
      const url = new URL(request.url);
      asked.push(url.searchParams.get("after_seq"));
      expect(url.searchParams.get("limit")).toBe("1000");
      return url.searchParams.get("after_seq") === "2"
        ? HttpResponse.json({ events: [ev(3)], next_after_seq: null })
        : HttpResponse.json({ events: [ev(1), ev(2)], next_after_seq: 2 });
    }));
    const { events } = await fetchAllTaskEvents("con_1", "tsk_1");
    expect(events.map((e) => e.seq)).toEqual([1, 2, 3]);
    expect(asked).toEqual([null, "2"]);
  });

  it("stops after one call when the server does not paginate", async () => {
    let calls = 0;
    server.use(http.get("/v1/containers/con_1/tasks/tsk_1/events", () => {
      calls += 1;
      return HttpResponse.json({ events: [ev(1)] });
    }));
    const { events } = await fetchAllTaskEvents("con_1", "tsk_1");
    expect(events).toHaveLength(1);
    expect(calls).toBe(1);
  });
});
