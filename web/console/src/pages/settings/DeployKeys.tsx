import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useDeployKeys, useCreateDeployKey, useDeleteDeployKey, keys } from "../../api/queries";
import { ApiError } from "../../api/client";
import { useToast } from "../../components/Toast";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { CopyButton } from "../../components/CopyButton";
import { Button } from "../../ui/Button";
import { Field } from "../../ui/Field";
import { Input } from "../../ui/inputs";
import { Icons } from "../../ui/Icon";
import { EmptyRow } from "../../ui/EmptyState";
import { formatDate } from "../../lib/format";
import type { DeployKey } from "../../api/queries";

export default function DeployKeys() {
  const { data } = useDeployKeys();
  const create = useCreateDeployKey();
  const del = useDeleteDeployKey();
  const qc = useQueryClient();
  const toast = useToast();
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [created, setCreated] = useState<DeployKey | null>(null);
  const [removing, setRemoving] = useState<DeployKey | null>(null);
  const [rowError, setRowError] = useState<{ id: string; message: string } | null>(null);
  const rows = data ?? [];

  async function onCreate() {
    try {
      const key = await create.mutateAsync(name);
      setCreated(key);
      setCreating(false);
      setName("");
    } catch (err) {
      toast.error("Couldn't generate deploy key", err instanceof ApiError ? err.message : undefined);
    }
  }

  async function onDelete(k: DeployKey) {
    try {
      await del.mutateAsync(k.id);
      toast.success(`Deleted ${k.name}`);
      qc.invalidateQueries({ queryKey: keys.deployKeys });
      setRowError(null);
      setRemoving(null);
    } catch (err) {
      if (err instanceof ApiError && err.code === "deploy_key_in_use") {
        setRowError({ id: k.id, message: err.message });
        setRemoving(null);
      } else {
        toast.error("Couldn't delete deploy key", err instanceof ApiError ? err.message : undefined);
      }
    }
  }

  return (
    <div className="page">
      {/* Header */}
      <div className="page-title" style={{ display: "flex", alignItems: "flex-end", gap: 12 }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <h1 style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-0.02em", margin: 0 }}>Deploy keys</h1>
            <span className="pill pill-dormant" style={{ fontWeight: 500 }}>
              {rows.length} {rows.length === 1 ? "key" : "keys"}
            </span>
          </div>
          <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 4 }}>
            SSH keypairs that give a skill read-only clone access to a private GitHub repo.
            The private key is generated and stored server-side — only the public key is ever shown.
          </div>
        </div>
        <div style={{ marginLeft: "auto" }}>
          <Button
            variant={creating ? "secondary" : "primary"}
            size="sm"
            style={{ gap: 6, padding: "6px 12px 6px 10px" }}
            onClick={() => setCreating((v) => !v)}
          >
            {creating ? "Close" : (<><Icons.Plus w={14} />Generate key</>)}
          </Button>
        </div>
      </div>

      {/* New deploy key form (inline) */}
      {creating && (
        <div className="card form-card">
          <h2>New deploy key</h2>
          <p className="form-card-sub">
            Generates an SSH keypair. The private key is never shown or sent anywhere — only the public
            half comes back, once, right after creation.
          </p>
          <Field label="Name" htmlFor="dkn" hint="A label to recognise which repo this key is for.">
            <Input
              id="dkn"
              placeholder="team"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </Field>
          <div className="form-card-actions">
            <Button variant="secondary" size="sm" onClick={() => setCreating(false)}>
              Cancel
            </Button>
            <Button variant="dark" size="sm" disabled={!name || create.isPending} onClick={onCreate}>
              Generate key
            </Button>
          </div>
        </div>
      )}

      {/* Newly generated key — emphasized, with GitHub setup instructions */}
      {created && (
        <div className="card form-card">
          <h2>Add "{created.name}" to GitHub</h2>
          <p className="form-card-sub">
            Add this as a deploy key on the GitHub repo (Settings &rarr; Deploy keys &rarr; Add deploy key).
            Leave &lsquo;Allow write access&rsquo; unchecked.
          </p>
          <div
            className="mono"
            style={{
              background: "var(--surface-2)",
              borderRadius: 8,
              padding: "10px 12px",
              fontSize: 12.5,
              overflowWrap: "anywhere",
              marginBottom: 10,
            }}
          >
            {created.ssh_public_key}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <CopyButton text={created.ssh_public_key} label="Copy public key" />
            <span style={{ fontSize: 12, color: "var(--muted)" }}>{created.key_fingerprint}</span>
          </div>
          <div className="form-card-actions">
            <Button variant="secondary" size="sm" onClick={() => setCreated(null)}>
              Done
            </Button>
          </div>
        </div>
      )}

      {/* Deploy keys card */}
      <div className="card flush">
        <div className="tbl-wrap">
        <table className="tbl">
          <thead>
            <tr>
              <th>Name</th>
              <th>Fingerprint</th>
              <th>Created</th>
              <th style={{ width: 220, textAlign: "right" }} />
            </tr>
          </thead>
          <tbody>
            {rows.map((k) => (
              <tr key={k.id}>
                <td style={{ fontWeight: 600 }}>{k.name}</td>
                <td>
                  <span className="chip" style={{ fontSize: 11.5, padding: "4px 8px" }}>
                    <Icons.Key w={12} /> {k.key_fingerprint}
                  </span>
                </td>
                <td style={{ fontSize: 12.5, color: "var(--muted)" }}>{formatDate(k.created_at)}</td>
                <td style={{ textAlign: "right" }}>
                  <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 8 }}>
                    <CopyButton text={k.ssh_public_key} label="Copy public key" />
                    <Button variant="danger" size="sm" onClick={() => { setRemoving(k); setRowError(null); }}>
                      Delete
                    </Button>
                  </div>
                  {rowError?.id === k.id && (
                    <div style={{ marginTop: 6, fontSize: 12, color: "var(--err-700)", textAlign: "right" }}>
                      {rowError.message}
                    </div>
                  )}
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <EmptyRow
                colSpan={4}
                icon="Key"
                title="No deploy keys yet"
                description="Generate a key to give a skill read-only clone access to a private repo."
              />
            )}
          </tbody>
        </table>
        </div>
      </div>

      <ConfirmDialog
        open={!!removing}
        title="Delete deploy key"
        body={`Delete "${removing?.name}"? Skills using it for git access will stop working.`}
        confirmLabel="Delete key"
        onConfirm={() => removing && onDelete(removing)}
        onCancel={() => setRemoving(null)}
      />
    </div>
  );
}
