import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "../../auth/useAuth";
import { api, ApiError } from "../../api/client";
import { keys } from "../../api/queries";
import { useToast } from "../../components/Toast";
import { clearLog } from "../../apiLog/store";
import ChangePassword from "../ChangePassword";
import { Avatar } from "../../ui/Avatar";
import { Button } from "../../ui/Button";
import { Card } from "../../ui/Card";
import { Pill } from "../../ui/Pill";
import { Input } from "../../ui/inputs";
import { Icons } from "../../ui/Icon";
import type { Role } from "../../api/types";

const ROLE_TONE: Record<Role, "ink" | "info" | "dormant"> = {
  owner: "ink",
  admin: "info",
  member: "dormant",
};

export default function Profile() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();

  const original = user?.name ?? "";
  const [name, setName] = useState(original);
  const [saving, setSaving] = useState(false);

  const trimmed = name.trim();
  const dirty = trimmed !== original;
  const canSave = dirty && trimmed.length > 0 && !saving;

  async function signOut() {
    await api.post("/v1/auth/logout").catch(() => {});
    clearLog();
    qc.clear();
    navigate("/login", { replace: true });
  }

  async function saveName() {
    if (!canSave) return;
    setSaving(true);
    try {
      await api.patch(`/v1/users/${user?.id}`, { name: trimmed });
      toast.success("Profile updated");
      qc.invalidateQueries({ queryKey: keys.me });
    } catch (err) {
      toast.error("Couldn't update profile", err instanceof ApiError ? err.message : undefined);
    } finally {
      setSaving(false);
    }
  }

  async function copyId() {
    if (!user?.id) return;
    try {
      await navigator.clipboard.writeText(user.id);
      toast.success("User ID copied");
    } catch {
      toast.error("Couldn't copy");
    }
  }

  const role = (user?.role ?? "member") as Role;

  return (
    <div className="page">
      {/* Page header */}
      <div className="page-title">
          <h1 style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-0.02em", margin: 0 }}>Profile</h1>
          <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 4 }}>
            Manage your account identity, password, and session.
          </div>
        </div>

        {/* Identity card */}
        <Card>
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            <Avatar name={user?.name} size={56} />
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ fontSize: 18, fontWeight: 800, letterSpacing: "-0.01em", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {user?.name || "Unnamed user"}
              </div>
              <div style={{ fontSize: 13, color: "var(--muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {user?.email}
              </div>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 6, flex: "0 0 auto" }}>
              {user?.is_staff && <Pill tone="warn">Staff</Pill>}
              <Pill tone={ROLE_TONE[role]} style={{ textTransform: "capitalize" }}>{role}</Pill>
            </div>
          </div>

          <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8, marginTop: 16, paddingTop: 16, borderTop: "1px solid var(--border)" }}>
            {user?.tenant?.name && (
              <span className="chip" style={{ gap: 6 }}>
                <Icons.Server w={12} /> {user.tenant.name}
              </span>
            )}
            <button
              type="button"
              className="chip"
              onClick={copyId}
              title="Copy user ID"
              aria-label="Copy user ID"
              style={{ cursor: "pointer", gap: 6 }}
            >
              <Icons.Copy w={12} /> <b>{user?.id ?? "—"}</b>
            </button>
          </div>
        </Card>

        {/* Display name */}
        <section className="section-card">
          <div className="section-card-head">
            <span className="section-card-ico"><Icons.Profile w={16} /></span>
            <div className="section-card-titles">
              <div className="section-card-title">Display name</div>
              <div className="section-card-hint">Shown across the console and on activity you create.</div>
            </div>
          </div>
          <div className="section-card-body" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <Input
              aria-label="Display name"
              placeholder="Your name"
              value={name}
              maxLength={120}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") saveName(); }}
              style={{ maxWidth: 360 }}
            />
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <Button variant="dark" size="sm" onClick={saveName} disabled={!canSave}>
                {saving ? "Saving…" : "Save changes"}
              </Button>
              {dirty && !saving && (
                <Button variant="ghost" size="sm" onClick={() => setName(original)}>
                  Cancel
                </Button>
              )}
              {dirty && (
                <span style={{ marginLeft: "auto", fontSize: 12, color: "var(--muted)" }}>
                  Unsaved changes
                </span>
              )}
            </div>
          </div>
        </section>

        {/* Password */}
        <section className="section-card">
          <div className="section-card-head">
            <span className="section-card-ico"><Icons.Key w={16} /></span>
            <div className="section-card-titles">
              <div className="section-card-title">Password</div>
              <div className="section-card-hint">Use a strong password you don't reuse elsewhere.</div>
            </div>
          </div>
          <div className="section-card-body">
            <div style={{ maxWidth: 360 }}>
              <ChangePassword forced={false} bare />
            </div>
          </div>
        </section>

        {/* Sign out — separated destructive action */}
        <section className="section-card" style={{ borderColor: "var(--err-100)" }}>
          <div className="section-card-head" style={{ borderBottom: 0 }}>
            <span className="section-card-ico" style={{ background: "var(--err-100)", color: "var(--err-700)" }}>
              <Icons.Logout w={16} />
            </span>
            <div className="section-card-titles">
              <div className="section-card-title">Sign out</div>
              <div className="section-card-hint">End your session on this device.</div>
            </div>
            <div className="spacer" />
            <Button variant="danger" size="sm" onClick={signOut} style={{ gap: 6 }}>
              <Icons.Logout w={14} /> Sign out
            </Button>
          </div>
        </section>
    </div>
  );
}
