import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { User } from "@/types";

type AuthState = User | null | false;

interface AuthCtx {
  user: AuthState;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthCtx>({ user: null, login: async () => {}, logout: async () => {} });

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthState>(null);

  useEffect(() => {
    const check = async () => {
      try {
        setUser((await api.get<User>("/auth/me")).data);
      } catch {
        try {
          setUser((await api.post<User>("/auth/refresh")).data);
        } catch {
          setUser(false);
        }
      }
    };
    check();
    const onExpired = () => { setUser(false); };
    window.addEventListener("uqc:session-expired", onExpired);
    return () => { window.removeEventListener("uqc:session-expired", onExpired); };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const { data } = await api.post<User>("/auth/login", { email, password });
    setUser(data);
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.post("/auth/logout");
    } finally {
      setUser(false);
    }
  }, []);

  return <AuthContext.Provider value={{ user, login, logout }}>{children}</AuthContext.Provider>;
}

export const useAuth = () => useContext(AuthContext);
