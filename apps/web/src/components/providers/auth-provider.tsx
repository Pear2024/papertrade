"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";

import { api, getToken, setToken } from "@/lib/api";
import { clearCoachLocalCache } from "@/lib/coach-settings";
import { ApiError, AuthUser } from "@/lib/types";

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  apiError: string | null;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, displayName: string) => Promise<void>;
  logout: () => void;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [apiError, setApiError] = useState<string | null>(null);
  const router = useRouter();
  const queryClient = useQueryClient();

  const clearUserScopedClientState = useCallback(() => {
    clearCoachLocalCache();
    queryClient.clear();
  }, [queryClient]);

  const refresh = useCallback(async () => {
    setLoading(true);
    setApiError(null);
    const token = getToken();
    if (!token) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      const me = await api.me();
      setUser(me);
    } catch (error) {
      setUser(null);
      if (error instanceof ApiError && error.status === 401) {
        setToken(null);
      } else {
        setApiError(
          error instanceof Error
            ? error.message
            : "Unable to reach the API. Check that the API service is running.",
        );
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const login = useCallback(async (email: string, password: string) => {
    clearUserScopedClientState();
    const result = await api.login({ email, password });
    setToken(result.access_token);
    setUser(result.user);
    router.push("/dashboard");
  }, [clearUserScopedClientState, router]);

  const register = useCallback(
    async (email: string, password: string, displayName: string) => {
      clearUserScopedClientState();
      const result = await api.register({
        email,
        password,
        display_name: displayName,
      });
      setToken(result.access_token);
      setUser(result.user);
      router.push("/dashboard");
    },
    [clearUserScopedClientState, router],
  );

  const logout = useCallback(() => {
    clearUserScopedClientState();
    setToken(null);
    setUser(null);
    router.push("/login");
  }, [clearUserScopedClientState, router]);

  const value = useMemo(
    () => ({
      user,
      loading,
      apiError,
      isAuthenticated: !!user,
      login,
      register,
      logout,
      refresh,
    }),
    [user, loading, apiError, login, register, logout, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
