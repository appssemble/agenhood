import { useState } from "react";
import { createPortal } from "react-dom";
import { Button } from "../ui/Button";
import { Avatar } from "../ui/Avatar";
import { Icons } from "../ui/Icon";
import { useToast } from "./Toast";
import { useAuth } from "../auth/useAuth";
import { useCreateTenant } from "../api/queries";

export function CreateWorkspaceDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (id: string, name: string) => void;
}) {
  const create = useCreateTenant();
  const toast = useToast();
  const { user } = useAuth();
  const [name, setName] = useState("");

  if (!open) return null;

  async function submit() {
    const trimmed = name.trim();
    if (!trimmed || create.isPending) return;
    try {
      const res = await create.mutateAsync(trimmed);
      toast.success(`Workspace "${res.name}" created`);
      setName("");
      onClose();
      onCreated(res.id, res.name);
    } catch (e) {
      toast.error("Couldn't create workspace", e instanceof Error ? e.message : undefined);
    }
  }

  // Portaled into the main content column (`.fc-main`) rather than the header,
  // where it's mounted: the header's `.fc-ctxbar-center` has a `transform`,
  // which would make it the containing block for the overlay and push the panel
  // below the header, breaking the flush "drops from the header" seam. Anchoring
  // to `.fc-main` also centers the panel over the content area — aligned with
  // the header's search + tenant cluster — and tracks the nav-panel width.
  const host = document.querySelector(".fc-main") ?? document.body;
  return createPortal(
    <div
      className="cw-overlay"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="New workspace"
        className="cw-card"
        onKeyDown={(e) => { if (e.key === "Escape") onClose(); }}
      >
        <div className="cw-head">
          <h2 className="cw-title">Create a workspace</h2>
          <p className="cw-sub">An isolated home for your agents, containers, and team. You'll be its owner.</p>
        </div>

        <div className="cw-body">
          <label className="cw-label" htmlFor="ws-name">Workspace name</label>
          <input
            id="ws-name"
            className="cw-input"
            autoFocus
            placeholder="e.g. Acme Corp"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") submit(); }}
          />
          {user && (
            <div className="cw-owner">
              <Avatar name={user.name} size={30} />
              <span className="cw-owner-txt">
                <span className="cw-owner-role">You'll be the owner</span>
                <span className="cw-owner-email">{user.email}</span>
              </span>
            </div>
          )}
        </div>

        <div className="cw-foot">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={!name.trim() || create.isPending} onClick={submit}>
            {create.isPending ? (
              <><span className="cw-spin" aria-hidden="true" /> Creating…</>
            ) : (
              <>Create <Icons.ArrowRight w={14} /></>
            )}
          </Button>
        </div>
      </div>
    </div>,
    host,
  );
}
