import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { useLifecycle, keys } from "./queries";
import type { Container } from "./types";

function wrap(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

test("pause optimistically sets pausing then rolls back on error", async () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData(keys.container("ctr_1"), { id: "ctr_1", status: "running" } as Container);
  // Add a small delay so optimistic "pausing" state is observable before rollback
  server.use(http.post("*/v1/containers/ctr_1/pause", async () => {
    await new Promise(r => setTimeout(r, 50));
    return HttpResponse.json({ error: { code: "conflict", message: "running tasks" } }, { status: 409 });
  }));
  const { result } = renderHook(() => useLifecycle("ctr_1"), { wrapper: wrap(qc) });
  act(() => { result.current.pause.mutate(false); });
  await waitFor(() => expect((qc.getQueryData(keys.container("ctr_1")) as Container).status).toBe("pausing"));
  await waitFor(() => expect((qc.getQueryData(keys.container("ctr_1")) as Container).status).toBe("running"));
});
