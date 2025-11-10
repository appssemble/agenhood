import type { ReactNode } from "react";
import { useMe } from "../api/queries";
import { AuthContext } from "./useAuth";

export function AuthProvider({ children }: { children: ReactNode }) {
  const { data, isLoading } = useMe();
  return <AuthContext.Provider value={{ user: data ?? null, isLoading }}>{children}</AuthContext.Provider>;
}
