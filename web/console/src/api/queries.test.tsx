import { describe, it, expect } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import type { ReactNode } from "react";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { useSelectTenant, useAllTenants, useCreateTenant } from "./queries";

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  );
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
