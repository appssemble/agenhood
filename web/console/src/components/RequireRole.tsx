import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../auth/useAuth";
import type { Role } from "../api/types";

const RANK: Record<Role, number> = { member: 0, admin: 1, owner: 2 };

export function RequireRole({ min, staff, children }: { min?: Role; staff?: boolean; children: ReactNode }) {
  const { user, isLoading } = useAuth();
  if (isLoading) return <div className="p-8 text-sm text-muted">Loading…</div>;
  if (!user) return <Navigate to="/login" replace />;
  if (staff && !user.is_staff) return <Navigate to="/" replace />;
  if (min && !user.is_staff && RANK[user.role] < RANK[min]) return <Navigate to="/" replace />;
  return <>{children}</>;
}
