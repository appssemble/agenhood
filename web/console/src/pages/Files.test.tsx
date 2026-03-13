import { describe, it, expect, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../test/server";
import { renderWithProviders } from "../test/render";
import Files from "./Files";

vi.mock("react-router-dom", async (orig) => ({ ...(await orig<typeof import("react-router-dom")>()), useParams: () => ({ cid: "con_1" }) }));

function mockContainer(status = "running") {
  server.use(http.get("/v1/containers/con_1", () => HttpResponse.json({
    id: "con_1", name: "My Box", external_id: null, status,
    image_variant: "slim", image_tag: "v",
    config: { driver: "vanilla", model: "m", system_prompt: "", system_prompt_mode: "augment", tools: [], context: { variables: {}, text: null, files: [] } },
    metadata: {}, last_task_at: null, created_at: "t", error_message: null,
  })));
}

describe("Files", () => {
  it("lists files with a download link", async () => {
    mockContainer();
    server.use(http.get("/v1/containers/con_1/files", () => HttpResponse.json({ files: [
      { path: "/workspace/reports/q3-summary.md", size: 5400, modified_at: "t", content_type: "text/markdown" },
    ] })));
    renderWithProviders(<Files />);
    expect(await screen.findByText("q3-summary.md")).toBeInTheDocument();
    const dl = screen.getByRole("link", { name: /^Download q3-summary\.md$/i });
    // buildFileTree yields the workspace-relative path (no leading slash) — a
    // leading slash is treated as a path escape by the files API.
    expect(dl).toHaveAttribute("href", expect.stringContaining("/v1/containers/con_1/files/raw?path=workspace%2Freports%2Fq3-summary.md"));
  });

  it("auto-previews a text file's contents when it is selected", async () => {
    mockContainer();
    server.use(http.get("/v1/containers/con_1/files", () => HttpResponse.json({ files: [
      { path: "/workspace/notes.md", size: 40, modified_at: "t", content_type: "text/markdown" },
    ] })));
    server.use(http.get("/v1/containers/con_1/files/raw", () =>
      new HttpResponse("# Title\n\nHello from the preview", {
        headers: { "content-type": "application/octet-stream" },
      })));
    renderWithProviders(<Files />);
    await userEvent.click(await screen.findByText("notes.md"));
    expect(await screen.findByText(/Hello from the preview/)).toBeInTheDocument();
  });

  it("deletes a file via DELETE after confirming", async () => {
    mockContainer();
    server.use(http.get("/v1/containers/con_1/files", () => HttpResponse.json({ files: [
      { path: "/workspace/reports/q3-summary.md", size: 5400, modified_at: "t", content_type: "text/markdown" },
    ] })));
    let deletedPath: string | null = null;
    server.use(http.delete("/v1/containers/con_1/files/raw", ({ request }) => {
      deletedPath = new URL(request.url).searchParams.get("path");
      return new HttpResponse(null, { status: 204 });
    }));
    renderWithProviders(<Files />);
    await userEvent.click(await screen.findByRole("button", { name: /^Delete q3-summary\.md$/i }));
    // Confirm dialog appears; confirm the deletion.
    await userEvent.click(await screen.findByRole("button", { name: /^Delete file$/i }));
    // buildFileTree yields the workspace-relative path (no leading slash), which
    // is what the files API expects — a leading slash is treated as a path escape.
    await waitFor(() => expect(deletedPath).toBe("workspace/reports/q3-summary.md"));
  });

  it("shows an empty folder and uploads a file into it", async () => {
    mockContainer();
    server.use(http.get("/v1/containers/con_1/files", () => HttpResponse.json({ files: [
      { path: "reports", size: 0, is_dir: true, modified_at: "t", content_type: "" },
    ] })));
    let uploadedPath: string | null = null;
    server.use(http.put("/v1/containers/con_1/files/raw", ({ request }) => {
      uploadedPath = new URL(request.url).searchParams.get("path");
      return new HttpResponse(null, { status: 204 });
    }));
    renderWithProviders(<Files />);
    // The empty folder is visible even though it holds no files.
    expect(await screen.findByText("reports")).toBeInTheDocument();
    const input = await screen.findByLabelText(/^Upload to reports$/i);
    const file = new File(["x"], "new.txt", { type: "text/plain" });
    await userEvent.upload(input as HTMLInputElement, file);
    await waitFor(() => expect(uploadedPath).toBe("reports/new.txt"));
  });

  it("deletes a folder recursively after confirming", async () => {
    mockContainer();
    server.use(http.get("/v1/containers/con_1/files", () => HttpResponse.json({ files: [
      { path: "reports", size: 0, is_dir: true, modified_at: "t", content_type: "" },
      { path: "reports/q3.md", size: 12, is_dir: false, modified_at: "t", content_type: "text/markdown" },
    ] })));
    let deletedPath: string | null = null;
    server.use(http.delete("/v1/containers/con_1/files/raw", ({ request }) => {
      deletedPath = new URL(request.url).searchParams.get("path");
      return new HttpResponse(null, { status: 204 });
    }));
    renderWithProviders(<Files />);
    await userEvent.click(await screen.findByRole("button", { name: /^Delete folder reports$/i }));
    await userEvent.click(await screen.findByRole("button", { name: /^Delete folder$/i }));
    await waitFor(() => expect(deletedPath).toBe("reports"));
  });

  it("resizes the file tree via the draggable separator (keyboard)", async () => {
    mockContainer();
    server.use(http.get("/v1/containers/con_1/files", () => HttpResponse.json({ files: [
      { path: "notes.md", size: 5, is_dir: false, modified_at: "t", content_type: "text/markdown" },
    ] })));
    renderWithProviders(<Files />);
    const sep = await screen.findByRole("separator", { name: /resize file tree/i });
    const before = Number(sep.getAttribute("aria-valuenow"));
    sep.focus();
    await userEvent.keyboard("{ArrowRight}");
    await waitFor(() =>
      expect(Number(sep.getAttribute("aria-valuenow"))).toBeGreaterThan(before),
    );
  });

  it("uploads a chosen file via PUT", async () => {
    mockContainer();
    server.use(http.get("/v1/containers/con_1/files", () => HttpResponse.json({ files: [] })));
    let uploadedPath: string | null = null;
    server.use(http.put("/v1/containers/con_1/files/raw", ({ request }) => {
      uploadedPath = new URL(request.url).searchParams.get("path");
      return HttpResponse.json({});
    }));
    renderWithProviders(<Files />);
    const input = await screen.findByLabelText(/upload/i);
    const file = new File(["hi"], "notes.txt", { type: "text/plain" });
    await userEvent.upload(input as HTMLInputElement, file);
    await waitFor(() => expect(uploadedPath).toBe("/workspace/notes.txt"));
  });

  it("shows a Download workspace link to the archive when running", async () => {
    mockContainer("running");
    server.use(http.get("/v1/containers/con_1/files", () => HttpResponse.json({ files: [] })));
    renderWithProviders(<Files />);
    const link = await screen.findByRole("link", { name: /download workspace/i });
    expect(link).toHaveAttribute("href", expect.stringContaining("/v1/containers/con_1/files/archive"));
    expect(link).toHaveAttribute("download");
  });

  it("hides the Download workspace link when not running", async () => {
    mockContainer("paused");
    server.use(http.get("/v1/containers/con_1/files", () => HttpResponse.json({ files: [] })));
    renderWithProviders(<Files />);
    await waitFor(() => expect(screen.getByText(/No files yet/i)).toBeInTheDocument());
    expect(screen.queryByRole("link", { name: /download workspace/i })).not.toBeInTheDocument();
  });
});
