"use client";

import { createContext, useContext, ReactNode } from "react";
import { useAccountFeatures, FeatureMap } from "@/hooks/useAccountFeatures";

interface AccountFeaturesContextValue {
  features: FeatureMap;
  loading: boolean;
  isFeatureEnabled: (slug: string) => boolean;
  refresh: () => void;
}

const AccountFeaturesContext = createContext<AccountFeaturesContextValue>({
  features: {},
  loading: false,
  isFeatureEnabled: () => false,
  refresh: () => {},
});

export function AccountFeaturesProvider({ children }: { children: ReactNode }) {
  const value = useAccountFeatures();
  return (
    <AccountFeaturesContext.Provider value={value}>
      {children}
    </AccountFeaturesContext.Provider>
  );
}

export function useAccountFeaturesContext(): AccountFeaturesContextValue {
  return useContext(AccountFeaturesContext);
}
