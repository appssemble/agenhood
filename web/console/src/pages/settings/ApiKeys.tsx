import { useState, useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useApiKeys, useCreateApiKey, keys } from "../../api/queries";
import { api, ApiError } from "../../api/client";
import { useToast } from "../../components/Toast";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { OneTimeSecret } from "../../components/OneTimeSecret";
import { Button } from "../../ui/Button";
import { Pill } from "../../ui/Pill";
import { SegControl } from "../../ui/SegControl";
import { Avatar } from "../../ui/Avatar";
import { Field } from "../../ui/Field";
import { Input } from "../../ui/inputs";
import { Icons } from "../../ui/Icon";
import { EmptyRow } from "../../ui/EmptyState";
import { freshness } from "../../lib/freshness";
import { formatDate } from "../../lib/format";
import type { ApiKeyCreated, ApiKeyRow } from "../../api/types";

type SortKey = "last_used" | "created" | "name";

export default function ApiKeys() {
  const { data, error } = useApiKeys();
  const create = useCreateApiKey();
  const qc = useQueryClient();
  const toast = useToast();
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [revealed, setRevealed] = useState<ApiKeyCreated | null>(null);
  const [revoking, setRevoking] = useState<ApiKeyRow | null>(null);
  const [sort, setSort] = useState<SortKey>("last_used");
  const [showRevoked, setShowRevoked] = useState(false);
  const rows = data?.keys ?? [];

  const filtered = showRevoked ? rows : rows.filter((k) => k.status === "active");

  const sorted = useMemo(() => {
    const copy = [...filtered];
    if (sort === "name") return copy.sort((a, b) => a.name.localeCompare(b.name));
    if (sort === "created") return copy.sort((a, b) => b.created_at.localeCompare(a.created_at));
    // last_used desc, nulls last
    return copy.sort((a, b) => {
      if (!a.last_used_at && !b.last_used_at) return 0;
      if (!a.last_used_at) return 1;
      if (!b.last_used_at) return -1;
      return b.last_used_at.localeCompare(a.last_used_at);
    });
  }, [filtered, sort]);

  async function onCreate() {
    try {
      const k = await create.mutateAsync(name);
      setRevealed(k);
      setCreating(false);
      setName("");
    } catch (err) {
      toast.error("Couldn't create key", err instanceof ApiError ? err.message : undefined);
    }
  }

  async function onRevoke(k: ApiKeyRow) {
    try {
      await api.del(`/v1/api-keys/${k.id}`);
      toast.success(`Revoked ${k.name}`);
      qc.invalidateQueries({ queryKey: keys.apiKeys });
      setRevoking(null);
    } catch (err) {
      toast.error("Couldn't revoke key", err instanceof ApiError ? err.message : undefined);
    }
  }

  return (
    <div className="page">
      {/* Header */}
      <div className="page-title">
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <h1 style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-0.02em", margin: 0 }}>API keys</h1>
          <span className="pill pill-dormant" style={{ fontWeight: 500 }}>
            {sorted.length} {sorted.length === 1 ? "key" : "keys"}
          </span>
        </div>
        <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 4 }}>
          Programmatic credentials for machine access to the agenhood API.
        </div>
      </div>

      {/* Toolbar: sort (left) + filter + New key (right) */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 12, color: "var(--muted)" }}>Sort by</span>
        <SegControl<SortKey>
          value={sort}
          onChange={setSort}
          options={[
            { value: "last_used", label: "Last used" },
            { value: "created", label: "Date added" },
            { value: "name", label: "Name" },
          ]}
        />
        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          <Button
            variant="secondary"
            size="sm"
            style={{ gap: 6, padding: "8px 12px 8px 10px" }}
            onClick={() => setShowRevoked((v) => !v)}
          >
            <Icons.Filter w={14} />
            {showRevoked ? "Active only" : "All keys"}
          </Button>
          <Button
            variant={creating ? "secondary" : "primary"}
            size="sm"
            style={{ gap: 6, padding: "8px 12px 8px 10px" }}
            onClick={() => setCreating((v) => !v)}
          >
            {creating ? "Close" : (<><Icons.Plus w={14} />New key</>)}
          </Button>
        </div>
      </div>

      {/* New key card (inline) */}
      {creating && (
        <div className="card form-card">
          <h2>New API key</h2>
          <p className="form-card-sub">
            The full secret is shown only once, right after you create it.
          </p>
          <Field label="Name" htmlFor="kn" hint="A label to recognise where this key is used.">
            <Input
              id="kn"
              placeholder="ci-deploy"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </Field>
          <div className="form-card-actions">
            <Button variant="secondary" size="sm" onClick={() => setCreating(false)}>
              Cancel
            </Button>
            <Button variant="dark" size="sm" disabled={!name} onClick={onCreate}>
              Create key
            </Button>
          </div>
        </div>
      )}

      {/* Keys card */}
      <div className="card flush">
        <div className="tbl-wrap">
        <table className="tbl">
          <thead>
            <tr>
              <th>Name</th>
              <th>Key</th>
              <th>Last used</th>
              <th>Created</th>
              <th>Created by</th>
              <th style={{ width: 120, textAlign: "right" }} />
            </tr>
          </thead>
          <tbody>
            {sorted.map((k) => {
              const { tone, label } = freshness(k.last_used_at);
              const revoked = k.status === "revoked";
              return (
                <tr key={k.id} style={revoked ? { opacity: 0.55 } : undefined}>
                  <td style={{ fontWeight: 600 }}>{k.name}</td>
                  <td>
                    <span className="chip" style={{ fontSize: 11.5, padding: "4px 8px" }}>
                      <Icons.Key w={12} /> {k.prefix}…
                    </span>
                  </td>
                  <td>
                    <Pill tone={tone}>
                      <span className="dot" /> {label}
                    </Pill>
                  </td>
                  <td style={{ fontSize: 12.5, color: "var(--muted)" }}>{formatDate(k.created_at)}</td>
                  <td>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <Avatar name={k.created_by} size={24} />
                      <span style={{ fontSize: 12.5 }}>{k.created_by}</span>
                    </div>
                  </td>
                  <td style={{ textAlign: "right" }}>
                    {revoked ? (
                      <Pill tone="dormant">Revoked</Pill>
                    ) : (
                      <Button variant="danger" size="sm" onClick={() => setRevoking(k)}>
                        Revoke
                      </Button>
                    )}
                  </td>
                </tr>
              );
            })}
            {error != null && (
              <EmptyRow
                colSpan={6}
                icon="Key"
                title="Couldn't load API keys"
                description={error instanceof ApiError ? error.message : "Something went wrong — try reloading."}
              />
            )}
            {error == null && sorted.length === 0 && (
              <EmptyRow
                colSpan={6}
                icon="Key"
                title={rows.length === 0 ? "No API keys yet" : "No active keys"}
                description={
                  rows.length === 0
                    ? "Create a key to access the agenhood API programmatically."
                    : "Switch to “All keys” to see previously issued keys."
                }
              />
            )}
          </tbody>
        </table>
        </div>
      </div>

      {revealed && (
        <OneTimeSecret secret={revealed.key} onDismiss={() => setRevealed(null)} />
      )}

      <ConfirmDialog
        open={!!revoking}
        title="Revoke API key"
        body={`Revoke "${revoking?.name}"? This takes effect immediately and cannot be undone.`}
        confirmLabel="Revoke key"
        onConfirm={() => revoking && onRevoke(revoking)}
        onCancel={() => setRevoking(null)}
      />
    </div>
  );
}
