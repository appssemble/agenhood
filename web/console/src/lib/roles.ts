import type { Me } from "../api/types";

/** Admin-capability predicate: staff, or an admin/owner role in the active
 *  tenant. Distinct from the RANK-based `RequireRole` route guard. */
export function isAdmin(user: Me | null | undefined): boolean {
  return !!user && (user.is_staff || user.role === "admin" || user.role === "owner");
}
