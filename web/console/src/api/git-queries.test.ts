import { describe, it, expect } from "vitest";
import React from "react";
import { renderHook, act, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import {
  keys, useGitRemoteKey, useVerifyGitRemote,
  useGitLink, useGitLinkKey, useVerifyGitLink,
  useLinkGitRepo, useRepullGitRepo, useUnlinkGitRepo,
} from "./queries";
import type { LinkedRepo } from "./types";

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(QueryClientProvider, { client: qc }, children);
  };
}

describe("git query keys", () => {
  it("scopes git keys under the container", () => {
    expect(keys.gitSnapshots("c1")).toEqual(["containers", "c1", "git", "snapshots"]);
    expect(keys.gitRemote("c1")).toEqual(["containers", "c1", "git", "remote"]);
    expect(keys.gitLink("c1")).toEqual(["containers", "c1", "git", "link"]);
  });
});

describe("useGitRemoteKey", () => {
  it("posts to the key endpoint and returns the public key", async () => {
    server.use(
      http.post("/v1/containers/c1/git/remote/key", () =>
        HttpResponse.json({ public_key: "ssh-ed25519 AAA", fingerprint: "SHA256:x", key_type: "ed25519" })
      )
    );
    const { result } = renderHook(() => useGitRemoteKey("c1"), { wrapper: makeWrapper() });
    let data: { public_key: string; fingerprint: string; key_type: string } | undefined;
    await act(async () => {
      data = await result.current.mutateAsync(false);
    });
    expect(data?.public_key).toBe("ssh-ed25519 AAA");
  });
});

describe("useVerifyGitRemote", () => {
  it("posts the url and returns branches", async () => {
    server.use(
      http.post("/v1/containers/c1/git/remote/verify", () =>
        HttpResponse.json({ ok: true, branches: ["main", "dev"], default_branch: "main" })
      )
    );
    const { result } = renderHook(() => useVerifyGitRemote("c1"), { wrapper: makeWrapper() });
    let data: { ok: boolean; branches: string[]; default_branch: string | null } | undefined;
    await act(async () => {
      data = await result.current.mutateAsync("git@github.com:a/b.git");
    });
    expect(data?.branches).toEqual(["main", "dev"]);
  });
});

const sampleLinked: LinkedRepo = {
  url: "git@github.com:a/b.git",
  branch: "main",
  ssh_public_key: "ssh-ed25519 AAA",
  key_fingerprint: "SHA256:x",
  key_type: "ed25519",
  verified_at: "2026-06-22T00:00:00Z",
  linked_at: "2026-06-22T00:00:00Z",
  last_clone_status: "ok",
  last_clone_error: null,
  last_clone_at: "2026-06-22T00:00:00Z",
};

describe("useGitLink", () => {
  it("gets the link endpoint and returns the linked repo", async () => {
    server.use(
      http.get("/v1/containers/c1/git/link", () =>
        HttpResponse.json({ linked: sampleLinked })
      )
    );
    const { result } = renderHook(() => useGitLink("c1"), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.linked?.url).toBe("git@github.com:a/b.git");
  });
});

describe("useGitLinkKey", () => {
  it("posts to the link key endpoint and returns the public key", async () => {
    server.use(
      http.post("/v1/containers/c1/git/link/key", () =>
        HttpResponse.json({ public_key: "ssh-ed25519 BBB", fingerprint: "SHA256:y", key_type: "ed25519" })
      )
    );
    const { result } = renderHook(() => useGitLinkKey("c1"), { wrapper: makeWrapper() });
    let data: { public_key: string; fingerprint: string; key_type: string } | undefined;
    await act(async () => {
      data = await result.current.mutateAsync(false);
    });
    expect(data?.public_key).toBe("ssh-ed25519 BBB");
  });

  it("appends rotate=true when rotating the link key", async () => {
    let url = "";
    server.use(
      http.post("/v1/containers/c1/git/link/key", ({ request }) => {
        url = request.url;
        return HttpResponse.json({ public_key: "ssh-ed25519 CCC", fingerprint: "SHA256:z", key_type: "ed25519" });
      })
    );
    const { result } = renderHook(() => useGitLinkKey("c1"), { wrapper: makeWrapper() });
    let data: { public_key: string; fingerprint: string; key_type: string } | undefined;
    await act(async () => {
      data = await result.current.mutateAsync(true);
    });
    expect(new URL(url).pathname + new URL(url).search).toBe("/v1/containers/c1/git/link/key?rotate=true");
    expect(data?.public_key).toBe("ssh-ed25519 CCC");
  });
});

describe("useVerifyGitLink", () => {
  it("posts the url and returns branches", async () => {
    let body: { url?: string } = {};
    server.use(
      http.post("/v1/containers/c1/git/link/verify", async ({ request }) => {
        body = (await request.json()) as typeof body;
        return HttpResponse.json({ ok: true, branches: ["main", "dev"], default_branch: "main" });
      })
    );
    const { result } = renderHook(() => useVerifyGitLink("c1"), { wrapper: makeWrapper() });
    let data: { ok: boolean; branches: string[]; default_branch: string | null } | undefined;
    await act(async () => {
      data = await result.current.mutateAsync("git@github.com:a/b.git");
    });
    expect(body).toEqual({ url: "git@github.com:a/b.git" });
    expect(data?.branches).toEqual(["main", "dev"]);
  });
});

describe("useLinkGitRepo", () => {
  it("posts url/branch with confirm:true baked in", async () => {
    let body: { url?: string; branch?: string; confirm?: boolean } = {};
    server.use(
      http.post("/v1/containers/c1/git/link", async ({ request }) => {
        body = (await request.json()) as typeof body;
        return HttpResponse.json({ linked: sampleLinked });
      })
    );
    const { result } = renderHook(() => useLinkGitRepo("c1"), { wrapper: makeWrapper() });
    let data: { linked: LinkedRepo } | undefined;
    await act(async () => {
      data = await result.current.mutateAsync({ url: "git@github.com:a/b.git", branch: "main" });
    });
    expect(body).toEqual({ url: "git@github.com:a/b.git", branch: "main", confirm: true });
    expect(data?.linked.branch).toBe("main");
  });
});

describe("useRepullGitRepo", () => {
  it("posts to the repull endpoint with confirm:true", async () => {
    let body: { confirm?: boolean } = {};
    server.use(
      http.post("/v1/containers/c1/git/link/repull", async ({ request }) => {
        body = (await request.json()) as typeof body;
        return HttpResponse.json({ linked: sampleLinked });
      })
    );
    const { result } = renderHook(() => useRepullGitRepo("c1"), { wrapper: makeWrapper() });
    await act(async () => {
      await result.current.mutateAsync();
    });
    expect(body).toEqual({ confirm: true });
  });
});

describe("useUnlinkGitRepo", () => {
  it("deletes the link endpoint", async () => {
    let called = false;
    server.use(
      http.delete("/v1/containers/c1/git/link", () => {
        called = true;
        return new HttpResponse(null, { status: 204 });
      })
    );
    const { result } = renderHook(() => useUnlinkGitRepo("c1"), { wrapper: makeWrapper() });
    await act(async () => {
      await result.current.mutateAsync();
    });
    expect(called).toBe(true);
  });
});
