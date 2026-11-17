"use client";

import { useState, useEffect, useRef } from "react";
import { useAuthToken } from "./useAuthToken";
import { useAccountContext } from "./useAccountContext";
import { UserPermissions } from "./types";

interface PermissionsState {
  permissions: UserPermissions | null;
  role: string | null;
  isPlatformAdmin: boolean;
  loading: boolean;
}

const FULL_PERMISSIONS: UserPermissions = {
  assistants: { view: true, create: true, edit: true, delete: true, publish: true },
  phone_numbers: { view: true, purchase: true, configure: true, release: true },
  call_logs: { view: true, view_transcripts: true, export: true, edit: true, delete: true },
  knowledge_base: { view: true, create: true, edit: true, delete: true, import: true },
  tools: { view: true, create: true, edit: true, delete: true },
  flows: { view: true, edit: true, publish: true, revert: true },
  team: { view: true, invite: true, manage_roles: true, remove: true },
  settings: { view: true, edit: true, billing: true, api_keys: true },
  integrations: { view: true, manage: true },
  usage: { view: true, export: true },
  records: { view: true, create: true, edit: true, delete: true, export: true, manage_types: true },
};

export const ANALYTICS_PERMISSION = { resource: "call_logs", action: "view" };

const EMPTY_PERMISSIONS: UserPermissions = {
  assistants: { view: false, create: false, edit: false, delete: false, publish: false },
  phone_numbers: { view: false, purchase: false, configure: false, release: false },
  call_logs: { view: false, view_transcripts: false, export: false, edit: false, delete: false },
  knowledge_base: { view: false, create: false, edit: false, delete: false, import: false },
  tools: { view: false, create: false, edit: false, delete: false },
  flows: { view: false, edit: false, publish: false, revert: false },
  team: { view: false, invite: false, manage_roles: false, remove: false },
  settings: { view: false, edit: false, billing: false, api_keys: false },
  integrations: { view: false, manage: false },
  usage: { view: false, export: false },
  records: { view: false, create: false, edit: false, delete: false, export: false, manage_types: false },
};

const CACHE_TTL_MS = 60_000;
const CACHE_KEY_PREFIX = "botelier_perm_cache_";

function readLocalCache(cacheKey: string): { data: PermissionsState; ts: number } | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(`${CACHE_KEY_PREFIX}${cacheKey}`);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function writeLocalCache(cacheKey: string, data: PermissionsState): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(
      `${CACHE_KEY_PREFIX}${cacheKey}`,
      JSON.stringify({ data, ts: Date.now() })
    );
  } catch {}
}

function deleteLocalCache(cacheKey: string): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.removeItem(`${CACHE_KEY_PREFIX}${cacheKey}`);
  } catch {}
}

function getInitialState(): PermissionsState {
  if (typeof window === "undefined") {
    return { permissions: null, role: null, isPlatformAdmin: false, loading: true };
  }
  try {
    const ctx = localStorage.getItem("botelier_account_context");
    if (!ctx) return { permissions: null, role: null, isPlatformAdmin: false, loading: true };
    const parsed = JSON.parse(ctx);
    const accountId = parsed?.accountId;
    if (!accountId) return { permissions: null, role: null, isPlatformAdmin: false, loading: true };
    const cached = readLocalCache(accountId);
    if (cached && Date.now() - cached.ts < CACHE_TTL_MS) {
      return cached.data;
    }
  } catch {}
  return { permissions: null, role: null, isPlatformAdmin: false, loading: true };
}

export function usePermissions(): PermissionsState & {
  can: (resource: keyof UserPermissions, action: string) => boolean;
  refresh: () => void;
} {
  const { token, authFetch } = useAuthToken();
  const { accountId } = useAccountContext();
  const [state, setState] = useState<PermissionsState>(getInitialState);
  const fetchedRef = useRef<string | null>(null);

  const cacheKey = `${accountId}`;

  const fetchPermissions = async () => {
    if (!token || !accountId) {
      setState({ permissions: EMPTY_PERMISSIONS, role: null, isPlatformAdmin: false, loading: false });
      return;
    }

    const cached = readLocalCache(cacheKey);
    if (cached && Date.now() - cached.ts < CACHE_TTL_MS) {
      setState(cached.data);
      return;
    }

    try {
      const res = await authFetch(
        `/api/admin/me/permissions?account_id=${accountId}`
      );
      if (res.ok) {
        const data = await res.json();
        const newState: PermissionsState = {
          permissions: data.is_platform_admin ? FULL_PERMISSIONS : (data.permissions ?? EMPTY_PERMISSIONS),
          role: data.role?.slug ?? null,
          isPlatformAdmin: data.is_platform_admin ?? false,
          loading: false,
        };
        writeLocalCache(cacheKey, newState);
        setState(newState);
      } else {
        setState({ permissions: EMPTY_PERMISSIONS, role: null, isPlatformAdmin: false, loading: false });
      }
    } catch {
      setState({ permissions: EMPTY_PERMISSIONS, role: null, isPlatformAdmin: false, loading: false });
    }
  };

  useEffect(() => {
    if (!accountId) return;
    if (fetchedRef.current === cacheKey) return;
    fetchedRef.current = cacheKey;
    fetchPermissions();
  }, [token, accountId]);

  const can = (resource: keyof UserPermissions, action: string): boolean => {
    if (state.isPlatformAdmin) return true;
    if (!state.permissions) return false;
    const res = state.permissions[resource] as Record<string, boolean> | undefined;
    if (!res) return false;
    return res[action] === true;
  };

  const refresh = () => {
    deleteLocalCache(cacheKey);
    fetchedRef.current = null;
    fetchPermissions();
  };

  return { ...state, can, refresh };
}
