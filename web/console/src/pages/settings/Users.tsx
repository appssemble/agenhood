import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useUsers, keys } from "../../api/queries";
import { api, ApiError } from "../../api/client";
import { useToast } from "../../components/Toast";
import { Button } from "../../ui/Button";
import { Pill } from "../../ui/Pill";
import { Avatar } from "../../ui/Avatar";
import { Field } from "../../ui/Field";
import { Input } from "../../ui/inputs";
import { Dropdown } from "../../ui/Dropdown";
import { Icons } from "../../ui/Icon";
import { EmptyRow } from "../../ui/EmptyState";
import type { Role } from "../../api/types";

const ROLE_OPTIONS = [
  { value: "member", label: "Member" },
  { value: "admin", label: "Admin" },
];

export default function Users() {
  const { data } = useUsers();
  const qc = useQueryClient();
  const toast = useToast();
  const [inviting, setInviting] = useState(false);
  const [form, setForm] = useState({ email: "", name: "", role: "member" as Role, password: "" });
  const users = data?.users ?? [];

  // Only active owners count toward the last-owner guard
  const activeOwners = users.filter((u) => u.role === "owner" && u.status === "active");
  const isLastActiveOwner = (uid: string) =>
    activeOwners.length === 1 && activeOwners[0].id === uid;

  async function invite() {
    try {
      await api.post("/v1/users", form);
      toast.success(`Invited ${form.name}`);
      qc.invalidateQueries({ queryKey: keys.users });
      setInviting(false);
      setForm({ email: "", name: "", role: "member", password: "" });
    } catch (err) {
      toast.error("Couldn't invite user", err instanceof ApiError ? err.message : undefined);
    }
  }

  async function setRole(uid: string, role: Role) {
    try {
      await api.patch(`/v1/users/${uid}`, { role });
      qc.invalidateQueries({ queryKey: keys.users });
    } catch (err) {
      toast.error("Couldn't update role", err instanceof ApiError ? err.message : undefined);
    }
  }

  return (
    <div className="page">
      {/* Header */}
      <div className="page-title" style={{ display: "flex", alignItems: "flex-end", gap: 12 }}>
        <div>
          <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-0.02em" }}>Users</div>
          <div style={{ fontSize: 13, color: "var(--muted)" }}>
            Manage who has access to this workspace and what they can do.
          </div>
        </div>
        <Button
          variant={inviting ? "secondary" : "primary"}
          size="sm"
          style={{ marginLeft: "auto" }}
          onClick={() => setInviting((v) => !v)}
        >
          {inviting ? "Close" : (<><Icons.Plus w={13} />Invite user</>)}
        </Button>
      </div>

      {/* Invite card (inline) */}
      {inviting && (
        <div className="card form-card">
          <h2>Invite user</h2>
          <p className="form-card-sub">
            They'll sign in with the email and temporary password you set here.
          </p>
          <div className="form-grid">
            <Field label="Full name" htmlFor="in">
              <Input
                id="in"
                placeholder="Jane Doe"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            </Field>
            <Field label="Email" htmlFor="ie">
              <Input
                id="ie"
                type="email"
                placeholder="jane@example.com"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
              />
            </Field>
            <Field label="Role" htmlFor="ir">
              <Dropdown
                id="ir"
                value={form.role}
                onChange={(v) => setForm({ ...form, role: v as Role })}
                options={ROLE_OPTIONS}
              />
            </Field>
            <Field label="Temporary password" htmlFor="ip" hint="They can change it after first sign-in.">
              <Input
                id="ip"
                type="password"
                placeholder="••••••••"
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
              />
            </Field>
          </div>
          <div className="form-card-actions">
            <Button variant="secondary" size="sm" onClick={() => setInviting(false)}>
              Cancel
            </Button>
            <Button
              variant="dark"
              size="sm"
              disabled={!form.email || !form.name || !form.password}
              onClick={invite}
            >
              Send invite
            </Button>
          </div>
        </div>
      )}

      {/* Users table */}
      <div className="card flush">
        <div className="tbl-wrap">
        <table className="tbl">
          <thead>
            <tr>
              <th>Member</th>
              <th style={{ width: 200 }}>Role</th>
              <th style={{ width: 130 }}>Status</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => {
              const lastOwner = isLastActiveOwner(u.id);
              return (
                <tr key={u.id}>
                  {/* Member: avatar + name + email */}
                  <td>
                    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                      <Avatar name={u.name} size={34} />
                      <div style={{ display: "flex", flexDirection: "column", gap: 1, minWidth: 0 }}>
                        <span style={{ fontWeight: 600, lineHeight: 1.3 }}>{u.name}</span>
                        <span style={{ fontSize: 12.5, color: "var(--muted)", lineHeight: 1.3 }}>
                          {u.email}
                        </span>
                      </div>
                    </div>
                  </td>

                  {/* Role */}
                  <td>
                    {u.role === "owner" ? (
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <Pill tone="ink">Owner</Pill>
                        {lastOwner && (
                          <span
                            className="id"
                            title="The last active owner can't change their role."
                            style={{ display: "inline-flex", alignItems: "center", gap: 4 }}
                          >
                            <Icons.Key w={11} /> Locked
                          </span>
                        )}
                      </div>
                    ) : (
                      <Dropdown
                        value={u.role}
                        onChange={(v) => setRole(u.id, v as Role)}
                        disabled={lastOwner}
                        width={160}
                        aria-label="Role"
                        options={ROLE_OPTIONS}
                      />
                    )}
                  </td>

                  {/* Status */}
                  <td>
                    <Pill tone={u.status === "active" ? "running" : "dormant"}>
                      <span className="dot" />
                      {u.status === "active" ? "Active" : "Disabled"}
                    </Pill>
                  </td>
                </tr>
              );
            })}
            {users.length === 0 && (
              <EmptyRow
                colSpan={3}
                icon="Users"
                title="No users yet"
                description="Invite a teammate to give them access."
              />
            )}
          </tbody>
        </table>
        </div>
      </div>
    </div>
  );
}
