"use client";

import { useEffect, useCallback, useState } from "react";

interface UseUnsavedChangesWarningProps {
  isDirty: boolean;
  onSave?: () => Promise<void>;
}

interface UnsavedChangesState {
  showModal: boolean;
  pendingNavigation: string | null;
}

export function useUnsavedChangesWarning({ isDirty, onSave }: UseUnsavedChangesWarningProps) {
  const [state, setState] = useState<UnsavedChangesState>({
    showModal: false,
    pendingNavigation: null,
  });

  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (isDirty) {
        e.preventDefault();
        e.returnValue = "";
        return "";
      }
    };

    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [isDirty]);

  const handleNavigate = useCallback((href: string): boolean => {
    if (isDirty) {
      setState({ showModal: true, pendingNavigation: href });
      return false;
    }
    return true;
  }, [isDirty]);

  const handleSaveAndNavigate = useCallback(async () => {
    if (onSave && state.pendingNavigation) {
      try {
        await onSave();
        window.location.href = state.pendingNavigation;
      } catch {
        setState({ showModal: false, pendingNavigation: null });
      }
    }
  }, [onSave, state.pendingNavigation]);

  const handleDiscardAndNavigate = useCallback(() => {
    if (state.pendingNavigation) {
      window.location.href = state.pendingNavigation;
    }
  }, [state.pendingNavigation]);

  const handleCancelNavigation = useCallback(() => {
    setState({ showModal: false, pendingNavigation: null });
  }, []);

  return {
    showModal: state.showModal,
    handleNavigate,
    handleSaveAndNavigate,
    handleDiscardAndNavigate,
    handleCancelNavigation,
  };
}
