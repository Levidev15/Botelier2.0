"use client";

import { useState, useCallback } from "react";

export interface WidgetDef {
  id: string;
  label: string;
  defaultVisible: boolean;
}

export function useWidgetLayout(pageKey: string, widgets: WidgetDef[]) {
  const storageKey = `botelier_widgets_${pageKey}`;

  const loadVisibility = (): Record<string, boolean> => {
    if (typeof window === "undefined") return {};
    try {
      const raw = localStorage.getItem(storageKey);
      if (raw) return JSON.parse(raw);
    } catch {}
    const defaults: Record<string, boolean> = {};
    widgets.forEach((w) => (defaults[w.id] = w.defaultVisible));
    return defaults;
  };

  const [visibility, setVisibility] = useState<Record<string, boolean>>(loadVisibility);

  const toggle = useCallback(
    (id: string) => {
      setVisibility((prev) => {
        const defaultVal = widgets.find((w) => w.id === id)?.defaultVisible ?? true;
        const current = prev[id] ?? defaultVal;
        const next = { ...prev, [id]: !current };
        localStorage.setItem(storageKey, JSON.stringify(next));
        return next;
      });
    },
    [storageKey, widgets]
  );

  const resetDefaults = useCallback(() => {
    const defaults: Record<string, boolean> = {};
    widgets.forEach((w) => (defaults[w.id] = w.defaultVisible));
    localStorage.setItem(storageKey, JSON.stringify(defaults));
    setVisibility(defaults);
  }, [storageKey, widgets]);

  const isVisible = (id: string) => visibility[id] ?? true;

  return { visibility, toggle, resetDefaults, isVisible };
}
