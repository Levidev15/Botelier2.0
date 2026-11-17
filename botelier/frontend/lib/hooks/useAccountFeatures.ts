"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useAuthToken } from "@/lib/auth/useAuthToken";
import { useAccountContext } from "@/lib/auth/useAccountContext";

export type FeatureMap = Record<string, boolean>;

interface UseAccountFeaturesResult {
  features: FeatureMap;
  loading: boolean;
  isFeatureEnabled: (slug: string) => boolean;
  refresh: () => void;
}

const EMPTY: FeatureMap = {};
const cache: Record<string, { data: FeatureMap; ts: number }> = {};
const CACHE_TTL_MS = 60_000;

export function useAccountFeatures(): UseAccountFeaturesResult {
  const { authFetch } = useAuthToken();
  const { accountId } = useAccountContext();
  const [features, setFeatures] = useState<FeatureMap>(EMPTY);
  const [loading, setLoading] = useState(false);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const fetchFeatures = useCallback(
    async (force = false) => {
      if (!accountId) return;

      const cached = cache[accountId];
      if (!force && cached && Date.now() - cached.ts < CACHE_TTL_MS) {
        setFeatures(cached.data);
        return;
      }

      setLoading(true);
      try {
        const res = await authFetch(`/api/account/features?account_id=${accountId}`);
        if (res.ok && mountedRef.current) {
          const data: FeatureMap = await res.json();
          cache[accountId] = { data, ts: Date.now() };
          setFeatures(data);
        }
      } catch {
      } finally {
        if (mountedRef.current) setLoading(false);
      }
    },
    [accountId, authFetch]
  );

  useEffect(() => {
    fetchFeatures();
  }, [fetchFeatures]);

  const isFeatureEnabled = useCallback(
    (slug: string): boolean => {
      return features[slug] === true;
    },
    [features]
  );

  const refresh = useCallback(() => {
    if (accountId) delete cache[accountId];
    fetchFeatures(true);
  }, [accountId, fetchFeatures]);

  return { features, loading, isFeatureEnabled, refresh };
}
