"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { getAccountContext } from "./accountContext";
import { clearAccountStorage, endMfaSession, redirectForMfa } from "./mfa-client";
import { signOut } from "next-auth/react";

const isBrowser = typeof window !== "undefined";

let globalToken: string | null = null;
let globalUser: any = null;
let isValidated = false;
let validationPromise: Promise<boolean> | null = null;

function safeGetItem(key: string): string | null {
  if (!isBrowser) return null;
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function safeSetItem(key: string, value: string): void {
  if (!isBrowser) return;
  try {
    localStorage.setItem(key, value);
  } catch {
    // Ignore storage errors
  }
}

function safeRemoveItem(key: string): void {
  if (!isBrowser) return;
  try {
    localStorage.removeItem(key);
  } catch {
    // Ignore storage errors
  }
}

export function useAuthToken() {
  const [token, setToken] = useState<string | null>(globalToken);
  const [user, setUser] = useState<any>(globalUser);
  const [loading, setLoading] = useState(!isValidated);
  const [error, setError] = useState<string | null>(null);
  const hasInitialized = useRef(false);

  const initializeAuth = useCallback(async () => {
    if (!isBrowser) {
      setLoading(false);
      return;
    }

    if (hasInitialized.current && isValidated) {
      setToken(globalToken);
      setUser(globalUser);
      setLoading(false);
      return;
    }

    hasInitialized.current = true;

    if (validationPromise) {
      await validationPromise;
      setToken(globalToken);
      setUser(globalUser);
      setLoading(false);
      return;
    }

    const storedToken = safeGetItem("botelier_token");
    const storedUser = safeGetItem("botelier_user");

    if (!storedToken) {
      globalToken = null;
      globalUser = null;
      isValidated = true;
      setToken(null);
      setUser(null);
      setError("Not authenticated");
      setLoading(false);
      return;
    }

    if (storedUser) {
      try {
        globalUser = JSON.parse(storedUser);
        setUser(globalUser);
      } catch (e) {
        console.error("Failed to parse stored user:", e);
      }
    }

    globalToken = storedToken;
    setToken(storedToken);
    isValidated = true;
    setLoading(false);
  }, []);

  useEffect(() => {
    initializeAuth();
  }, [initializeAuth]);

  useEffect(() => {
    const refresh = () => {
      globalToken = safeGetItem("botelier_token");
      try { globalUser = JSON.parse(safeGetItem("botelier_user") || "null"); } catch { globalUser = null; }
      setToken(globalToken);
      setUser(globalUser);
    };
    window.addEventListener("botelier-auth-changed", refresh);
    window.addEventListener("storage", refresh);
    return () => {
      window.removeEventListener("botelier-auth-changed", refresh);
      window.removeEventListener("storage", refresh);
    };
  }, []);

  const validateToken = useCallback(async (): Promise<boolean> => {
    const storedToken = safeGetItem("botelier_token");
    if (!storedToken) return false;

    try {
      const res = await fetch("/api/auth/validate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: storedToken }),
      });

      if (res.ok) {
        const data = await res.json();
        if (data.mfa_required) {
          window.location.assign("/security");
          return false;
        }
        if (data.valid) {
          if (data.user) {
            globalUser = data.user;
            setUser(data.user);
            safeSetItem("botelier_user", JSON.stringify(data.user));
          }
          return true;
        }
      }
      if (await redirectForMfa(res)) return false;

      safeRemoveItem("botelier_token");
      safeRemoveItem("botelier_user");
      globalToken = null;
      globalUser = null;
      isValidated = false;
      setToken(null);
      setUser(null);
      return false;
    } catch (err) {
      console.error("Token validation error:", err);
      return false;
    }
  }, []);

  const authFetch = useCallback(
    async (url: string, options: RequestInit = {}) => {
      const currentToken = globalToken || safeGetItem("botelier_token");

      if (!currentToken) {
        throw new Error("Not authenticated");
      }

      const headers: Record<string, string> = {
        Authorization: `Bearer ${currentToken}`,
      };

      if (!(options.body instanceof FormData)) {
        headers["Content-Type"] = "application/json";
      }

      const accountContext = getAccountContext();
      if (accountContext?.isAdminSession && accountContext.sessionToken) {
        headers["X-Support-Session"] = accountContext.sessionToken;
        headers["X-Account-Id"] = accountContext.accountId;
      }

      const response = await fetch(url, {
        ...options,
        headers: {
          ...headers,
          ...options.headers,
        },
      });

      if (await redirectForMfa(response)) return response;
      if (response.status === 401) {
        safeRemoveItem("botelier_token");
        safeRemoveItem("botelier_user");
        globalToken = null;
        globalUser = null;
        isValidated = false;
        if (typeof window !== "undefined") {
          window.location.href = "/login?callbackUrl=/dashboard&reason=session_expired";
        }
      }

      return response;
    },
    []
  );

  const logout = useCallback(async () => {
    // Do not claim successful logout while a live server session remains.
    await endMfaSession();
    await signOut({ redirect: false });
    clearAccountStorage();
    safeRemoveItem("botelier_token");
    safeRemoveItem("botelier_user");
    globalToken = null;
    globalUser = null;
    isValidated = false;
    setToken(null);
    setUser(null);
  }, []);

  const getUser = useCallback(() => {
    if (globalUser) return globalUser;
    const storedUser = safeGetItem("botelier_user");
    if (storedUser) {
      try {
        globalUser = JSON.parse(storedUser);
        return globalUser;
      } catch (e) {
        return null;
      }
    }
    return null;
  }, []);

  return {
    token,
    user: user || getUser(),
    loading,
    error,
    authFetch,
    validateToken,
    logout,
    isAuthenticated: !!token
  };
}
