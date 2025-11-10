import { createContext, useContext } from "react";
import type { Me } from "../api/types";

export interface AuthValue { user: Me | null; isLoading: boolean; }
export const AuthContext = createContext<AuthValue>({ user: null, isLoading: true });
export const useAuth = () => useContext(AuthContext);
