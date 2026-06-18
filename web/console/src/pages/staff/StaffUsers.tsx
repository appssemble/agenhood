import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useStaffUsers, useMe, keys } from "../../api/queries";
import { api, ApiError } from "../../api/client";
import { useToast } from "../../components/Toast";
import { Button } from "../../ui/Button";
import { Pill } from "../../ui/Pill";
import { Avatar } from "../../ui/Avatar";
import { Field } from "../../ui/Field";
import { Input } from "../../ui/inputs";
import { Icons } from "../../ui/Icon";
import { EmptyRow } from "../../ui/EmptyState";

const EMPTY = { email: "", name: "", password: "" };

function fmtDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? "—"
    : d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export default function StaffUsers() {
  const { data } = useStaffUsers();
  const me = useMe().data;
  const qc = useQueryClient();
  const toast = useToast();
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [form, setForm] = useState(EMPTY);
  const staff = data?.staff ?? [];

  async function create() {
    try {
      setBusy("create");
      await api.post("/admin/v1/staff", form);
      toast.success(`Added ${form.name}`);
      qc.invalidateQueries({ queryKey: keys.staffUsers });
      setAdding(false);
      setForm(EMPTY);
    } catch (err) {
      toast.error("Couldn't add staff user", err instanceof ApiError ? err.message : undefined);
    } finally {
      setBusy(null);
    }
  }

  async function setStatus(uid: string, status: "active" | "disabled") {
    try {
      setBusy(uid);
      await api.patch(`/admin/v1/staff/${uid}`, { status });
      qc.invalidateQueries({ queryKey: keys.staffUsers });
    } catch (err) {
      toast.error("Couldn't update staff user", err instanceof ApiError ? err.message : undefined);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="page">
      {/* Header */}
      <div className="page-title" style={{ display: "flex", alignItems: "flex-end", gap: 12 }}>
        <div>
          <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-0.02em" }}>Staff users</div>
          <div style={{ fontSize: 13, color: "var(--muted)" }}>
            Administrators with cross-workspace access. They sign in with email and password.
          </div>
        </div>
        <Button
          variant={adding ? "secondary" : "primary"}
          size="sm"
          style={{ marginLeft: "auto" }}
          onClick={() => setAdding((v) => !v)}
        >
          {adding ? "Close" : (<><Icons.Plus w={13} />Add staff</>)}
        </Button>
      </div>

      {/* Create card (inline) */}
      {adding && (
        <div className="card form-card">
          <h2>Add staff user</h2>
          <p className="form-card-sub">
            They'll sign in with the email and temporary password you set here, then choose a new
            password on first sign-in.
          </p>
          <div className="form-grid">
            <Field label="Full name" htmlFor="sn">
              <Input
                id="sn"
                placeholder="Jane Doe"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            </Field>
            <Field label="Email" htmlFor="se">
              <Input
                id="se"
                type="email"
                placeholder="jane@example.com"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
              />
            </Field>
            <Field label="Temporary password" htmlFor="sp" hint="They'll change it on first sign-in.">
              <Input
                id="sp"
                type="password"
                placeholder="••••••••"
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
              />
            </Field>
          </div>
          <div className="form-card-actions">
            <Button variant="secondary" size="sm" onClick={() => setAdding(false)}>
              Cancel
            </Button>
            <Button
              variant="dark"
              size="sm"
              disabled={!form.email || !form.name || !form.password || busy === "create"}
              onClick={create}
            >
              Add staff user
            </Button>
          </div>
        </div>
      )}

      {/* Staff table */}
      <div className="card flush">
        <div className="tbl-wrap">
          <table className="tbl">
            <thead>
              <tr>
                <th>Staff member</th>
                <th style={{ width: 200 }}>Status</th>
                <th style={{ width: 130 }}>Added</th>
                <th style={{ width: 150 }} />
              </tr>
            </thead>
            <tbody>
              {staff.map((u) => {
                const isSelf = me?.id === u.id;
                const disabled = u.status === "disabled";
                return (
                  <tr key={u.id}>
                    {/* Member */}
                    <td>
                      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                        <Avatar name={u.name} size={34} />
                        <div style={{ display: "flex", flexDirection: "column", gap: 1, minWidth: 0 }}>
                          <span style={{ fontWeight: 600, lineHeight: 1.3 }}>
                            {u.name}
                            {isSelf && <span className="id" style={{ marginLeft: 8 }}>You</span>}
                          </span>
                          <span style={{ fontSize: 12.5, color: "var(--muted)", lineHeight: 1.3 }}>
                            {u.email}
                          </span>
                        </div>
                      </div>
                    </td>

                    {/* Status */}
                    <td>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <Pill tone={disabled ? "dormant" : "running"}>
                          <span className="dot" />
                          {disabled ? "Disabled" : "Active"}
                        </Pill>
                        {u.must_change_password && !disabled && (
                          <span
                            className="id"
                            title="Hasn't set a password yet"
                            style={{ display: "inline-flex", alignItems: "center", gap: 4 }}
                          >
                            <Icons.Key w={11} /> Pending
                          </span>
                        )}
                      </div>
                    </td>

                    {/* Added */}
                    <td style={{ fontSize: 12.5, color: "var(--muted)" }}>{fmtDate(u.created_at)}</td>

                    {/* Action */}
                    <td style={{ textAlign: "right" }}>
                      {disabled ? (
                        <Button
                          variant="secondary"
                          size="sm"
                          disabled={busy === u.id}
                          onClick={() => setStatus(u.id, "active")}
                        >
                          Reactivate
                        </Button>
                      ) : (
                        <Button
                          variant="danger"
                          size="sm"
                          disabled={isSelf || busy === u.id}
                          title={isSelf ? "You can't deactivate yourself" : undefined}
                          onClick={() => setStatus(u.id, "disabled")}
                        >
                          Deactivate
                        </Button>
                      )}
                    </td>
                  </tr>
                );
              })}
              {staff.length === 0 && (
                <EmptyRow
                  colSpan={4}
                  icon="Users"
                  title="No staff users yet"
                  description="Add an administrator to give them cross-workspace access."
                />
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
