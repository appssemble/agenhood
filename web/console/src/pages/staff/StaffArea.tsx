import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import { Card } from "../../ui/Card";

interface Tenant { id: string; name: string; status: string; }
interface Health {
  status: string;
  tenants?: number;
  containers_running?: number;
  active_tasks?: number;
}

export default function StaffArea() {
  const tenants = useQuery({ queryKey: ["admin", "tenants"], queryFn: () => api.get<{ tenants: Tenant[] }>("/admin/v1/tenants") });
  const health = useQuery({ queryKey: ["admin", "health"], queryFn: () => api.get<Health>("/admin/v1/health") });

  const h = health.data;

  const stats: Array<{ label: string; value: string | number }> = [
    { label: "System health", value: h?.status ?? "…" },
    ...(h?.tenants != null ? [{ label: "Tenants", value: h.tenants }] : []),
    ...(h?.containers_running != null ? [{ label: "Containers running", value: h.containers_running }] : h == null ? [{ label: "Containers running", value: "…" }] : []),
    ...(h?.active_tasks != null ? [{ label: "Active tasks", value: h.active_tasks }] : []),
  ];

  return (
    <div className="page">
      {/* Page header */}
      <div>
        <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-0.02em" }}>Staff</div>
        <div style={{ fontSize: 13, color: "var(--muted)" }}>System administration overview.</div>
      </div>

      {/* Health stat tiles */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 12 }}>
        {stats.map((s) => (
          <Card key={s.label} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <span style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".08em", color: "var(--muted)" }}>
              {s.label}
            </span>
            <span style={{ fontSize: 24, fontWeight: 800, letterSpacing: "-0.02em" }}>
              {s.value}
            </span>
          </Card>
        ))}
      </div>

      {/* Tenants table */}
      <div>
        <div style={{ fontSize: 13.5, fontWeight: 600, color: "var(--ink-2)", marginBottom: 8 }}>Tenants</div>
        <Card flush>
          <table className="tbl">
            <thead>
              <tr>
                <th>Tenant</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {(tenants.data?.tenants ?? []).map((t) => (
                <tr key={t.id}>
                  <td style={{ fontWeight: 600 }}>{t.name}</td>
                  <td>
                    <span
                      className={`pill ${t.status === "active" ? "pill-running" : "pill-dormant"}`}
                      style={{ fontSize: 11 }}
                    >
                      <span className="dot" /> {t.status}
                    </span>
                  </td>
                </tr>
              ))}
              {tenants.data && tenants.data.tenants.length === 0 && (
                <tr>
                  <td colSpan={2} style={{ padding: "32px 14px", textAlign: "center", fontSize: 13, color: "var(--muted)" }}>
                    No tenants yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </Card>
      </div>
    </div>
  );
}
