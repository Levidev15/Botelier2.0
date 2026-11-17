"use client";

import { useState, useEffect, useCallback } from "react";
import {
  getAccountContext,
  setAccountContext as storeAccountContext,
  clearAccountContext,
  AccountContext
} from "./accountContext";

export function useAccountContext() {
  const [context, setContext] = useState<AccountContext | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const storedContext = getAccountContext();
    setContext(storedContext);
    setLoading(false);
  }, []);

  const accountId = context?.accountId || "";
  const isAdminSession = context?.isAdminSession || false;
  const accountName = context?.accountName || null;

  const exitAccount = useCallback(() => {
    clearAccountContext();
    setContext(null);
  }, []);

  const switchAccount = useCallback((newContext: AccountContext) => {
    storeAccountContext(newContext);
    setContext(newContext);
  }, []);

  const setAccountContext = useCallback((newContext: AccountContext) => {
    storeAccountContext(newContext);
    setContext(newContext);
  }, []);

  return {
    accountId,
    accountName,
    isAdminSession,
    context,
    loading,
    exitAccount,
    switchAccount,
    setAccountContext,
  };
}
