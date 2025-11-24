import { describe, it, expect } from "vitest";
import { consoleWsUrl } from "./consoleSocket";

describe("consoleWsUrl", () => {
  it("builds a same-origin ws URL from window.location", () => {
    const url = consoleWsUrl("con_1", { protocol: "http:", host: "localhost:5173" }, "");
    expect(url).toBe("ws://localhost:5173/v1/containers/con_1/console");
  });

  it("uses wss when the page is https", () => {
    const url = consoleWsUrl("con_9", { protocol: "https:", host: "app.example.com" }, "");
    expect(url).toBe("wss://app.example.com/v1/containers/con_9/console");
  });

  it("derives ws host from an explicit http API base", () => {
    const url = consoleWsUrl("con_2", { protocol: "https:", host: "ignored" }, "http://api.local:8000");
    expect(url).toBe("ws://api.local:8000/v1/containers/con_2/console");
  });

  it("prefers an explicit ws base (dev direct-connect) over everything else", () => {
    const url = consoleWsUrl(
      "con_3",
      { protocol: "http:", host: "localhost:5173" },
      "http://api.local:8000",
      "ws://localhost:8443",
    );
    expect(url).toBe("ws://localhost:8443/v1/containers/con_3/console");
  });
});
