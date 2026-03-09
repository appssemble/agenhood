import { useRef } from "react";
import { useParams } from "react-router-dom";
import { useFiles, useContainer, keys } from "../api/queries";
import { useToast } from "../components/Toast";
import { ApiError } from "../api/client";
import { useQueryClient } from "@tanstack/react-query";
import { FileBrowser } from "../components/FileBrowser";
import { GitLinkPanel } from "../components/GitLinkPanel";
import { Icons } from "../ui/Icon";
import { EmptyState } from "../ui/EmptyState";
import { API_BASE as BASE } from "../api/base";
import { containerFileRawUrl } from "../api/fileUrls";

export default function Files() {
  const { cid } = useParams<{ cid: string }>();
  const { data, isLoading } = useFiles(cid!);
  const isRunning = useContainer(cid!).data?.status === "running";
  const qc = useQueryClient();
  const toast = useToast();
  const inputRef = useRef<HTMLInputElement>(null);

  async function handleUpload(file: File, dir = "/workspace") {
    const path = `${dir}/${file.name}`;
    try {
      const res = await fetch(
        containerFileRawUrl(cid!, path),
        { method: "PUT", credentials: "include", body: file },
      );
      if (!res.ok) throw new ApiError(`http_${res.status}`, "upload failed", res.status);
      toast.success(`Uploaded ${file.name}`);
      qc.invalidateQueries({ queryKey: keys.files(cid!, "") });
    } catch (err) {
      toast.error("Upload failed", err instanceof ApiError ? err.message : undefined);
    }
  }

  async function onInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    await handleUpload(file);
  }

  if (isLoading) return <div className="p-8 text-sm text-muted">Loading…</div>;
  const files = data?.files ?? [];

  return (
    <div style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0, gap: 16 }}>
      {cid && <GitLinkPanel cid={cid} />}
      <div
      style={{
        display: "flex",
        flexDirection: "column",
        flex: 1,
        minHeight: 0,
        overflow: "hidden",
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: "var(--r-3)",
      }}
    >
      {/* Upload toolbar */}
      <div
        style={{
          padding: "12px 18px",
          display: "flex",
          alignItems: "center",
          gap: 10,
          borderBottom: "1px solid var(--border)",
          background: "var(--surface)",
        }}
      >
        <span style={{ fontWeight: 700, fontSize: 13.5 }}>Files</span>
        <span className="id">{files.length} files</span>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          {isRunning && (
            <a
              className="btn btn-secondary btn-sm"
              href={`${BASE}/v1/containers/${cid}/files/archive`}
              download
              aria-label="Download workspace"
            >
              <Icons.Download w={12} /> Download workspace
            </a>
          )}
          <label style={{ cursor: "pointer" }}>
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => inputRef.current?.click()}
              type="button"
            >
              <Icons.Upload w={12} /> Upload
            </button>
            <input
              ref={inputRef}
              aria-label="Upload file"
              type="file"
              style={{ display: "none" }}
              onChange={onInputChange}
            />
          </label>
        </div>
      </div>

      {files.length === 0 ? (
        <div style={{ flex: 1, display: "flex" }}>
          <EmptyState
            icon="Folder"
            title="No files yet"
            description="Upload files or run a task. The container's workspace shows up here."
          />
        </div>
      ) : (
        <FileBrowser cid={cid!} files={files} onUpload={handleUpload} />
      )}
      </div>
    </div>
  );
}
