import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { renderWithProviders } from "../test/render";
import Console from "./Console";

vi.mock("react-router-dom", async (orig) => ({
  ...(await orig<typeof import("react-router-dom")>()),
  useParams: () => ({ cid: "con_1" }),
}));

// xterm renders to a real DOM/canvas; mock it down to the surface we use.
const writes: string[] = [];
const term = { open: 0, dispose: 0 }; // track lifecycle to catch stacked terminals
vi.mock("@xterm/xterm", () => ({
  Terminal: class {
    open() { term.open++; }
    write(d: unknown) {
      writes.push(d instanceof Uint8Array ? new TextDecoder().decode(d) : String(d));
    }
    onData(_cb: (d: string) => void) { return { dispose() {} }; }
    dispose() { term.dispose++; }
    get cols() { return 80; }
    get rows() { return 24; }
    loadAddon() {}
  },
}));
vi.mock("@xterm/addon-fit", () => ({
  FitAddon: class { fit() {} },
}));

class FakeWS {
  static last: FakeWS | null = null;
  url: string;
  binaryType = "";
  onopen: (() => void) | null = null;
  onclose: ((e: { code: number; reason: string }) => void) | null = null;
  onmessage: ((e: { data: unknown }) => void) | null = null;
  sent: unknown[] = [];
  closed = false;
  constructor(url: string) { this.url = url; FakeWS.last = this; }
  send(d: unknown) { this.sent.push(d); }
  close() { this.closed = true; this.onclose?.({ code: 1000, reason: "" }); }
}

function mockContainer(status = "running") {
  server.use(http.get("/v1/containers/con_1", () => HttpResponse.json({
    id: "con_1", name: "My Box", external_id: null, status,
    image_variant: "slim", image_tag: "v",
    config: { driver: "vanilla", model: "m", system_prompt: "", system_prompt_mode: "augment", tools: [], context: { variables: {}, text: null, files: [] } },
    metadata: {}, last_task_at: null, created_at: "t", error_message: null,
  })));
}

beforeEach(() => {
  writes.length = 0;
  term.open = 0;
  term.dispose = 0;
  FakeWS.last = null;
  vi.stubGlobal("WebSocket", FakeWS);
});

describe("Console", () => {
  it("disables the terminal when the container is not running", async () => {
    mockContainer("paused");
    renderWithProviders(<Console />);
    expect(await screen.findByText(/must be running/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /connect/i })).not.toBeInTheDocument();
  });

  it("connects on click and streams output into the terminal", async () => {
    mockContainer("running");
    renderWithProviders(<Console />);
    await userEvent.click(await screen.findByRole("button", { name: /^connect$/i }));
    await waitFor(() => expect(FakeWS.last).not.toBeNull());
    expect(FakeWS.last!.url).toContain("/v1/containers/con_1/console");
    FakeWS.last!.onopen?.();
    // Build the ArrayBuffer via the global constructor so `instanceof ArrayBuffer`
    // matches in jsdom (a real browser delivers a genuine ArrayBuffer here).
    const bytes = new TextEncoder().encode("hi\r\n");
    const ab = new ArrayBuffer(bytes.byteLength);
    new Uint8Array(ab).set(bytes);
    FakeWS.last!.onmessage?.({ data: ab });
    await waitFor(() => expect(writes.join("")).toContain("hi"));
  });

  it("disconnects and closes the socket", async () => {
    mockContainer("running");
    renderWithProviders(<Console />);
    await userEvent.click(await screen.findByRole("button", { name: /^connect$/i }));
    await waitFor(() => expect(FakeWS.last).not.toBeNull());
    FakeWS.last!.onopen?.();
    await userEvent.click(await screen.findByRole("button", { name: /disconnect/i }));
    expect(FakeWS.last!.closed).toBe(true);
  });

  it("does not stack terminals across reconnect (disposes the old one)", async () => {
    mockContainer("running");
    renderWithProviders(<Console />);
    await userEvent.click(await screen.findByRole("button", { name: /^connect$/i }));
    await waitFor(() => expect(term.open).toBe(1));
    await userEvent.click(await screen.findByRole("button", { name: /disconnect/i }));
    expect(term.dispose).toBe(1); // disconnect disposed the terminal
    await userEvent.click(await screen.findByRole("button", { name: /^connect$/i }));
    await waitFor(() => expect(term.open).toBe(2));
    // exactly one live terminal: every prior open has been disposed
    expect(term.open - term.dispose).toBe(1);
  });
});
