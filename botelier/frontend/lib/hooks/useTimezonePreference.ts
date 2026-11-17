"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { loadTimezone, saveTimezone } from "@/components/analytics/TimezonePicker";
import { useAuthToken } from "@/lib/auth/useAuthToken";

/**
 * Shared, persistent timezone preference.
 *
 * Resolution order:
 * 1. localStorage (instant, avoids a flash of the wrong timezone),
 * 2. the server-side per-user preference (survives sessions and devices),
 * 3. the browser's timezone as a final fallback (inside loadTimezone).
 *
 * Selecting a timezone writes BOTH localStorage and the server preference,
 * so every page using this hook (Records, Call Logs, Analytics) stays in sync.
 */
export function useTimezonePreference() {
  const { authFetch } = useAuthToken();
  const [timezone, setTimezoneState] = useState<string>("UTC");
  const fetchedServerPref = useRef(false);
  const userSelected = useRef(false);

  // Local value first for an instant, flash-free render.
  useEffect(() => {
    setTimezoneState(loadTimezone());
  }, []);

  // Then reconcile with the server-side preference once per mount.
  useEffect(() => {
    if (fetchedServerPref.current) return;
    fetchedServerPref.current = true;
    (async () => {
      try {
        const res = await authFetch("/api/auth/preferences");
        if (!res.ok) return;
        const prefs = await res.json();
        // If the user already picked a timezone while this fetch was in
        // flight, their fresh selection wins over the stale server value.
        if (userSelected.current) return;
        if (prefs && typeof prefs.timezone === "string" && prefs.timezone) {
          setTimezoneState(prefs.timezone);
          saveTimezone(prefs.timezone);
        }
      } catch {
        // Offline / unauthenticated — the localStorage value stands.
      }
    })();
  }, [authFetch]);

  const setTimezone = useCallback(
    (tz: string) => {
      userSelected.current = true;
      setTimezoneState(tz);
      saveTimezone(tz);
      // Persist server-side (best-effort; localStorage already updated).
      authFetch("/api/auth/preferences", {
        method: "PATCH",
        body: JSON.stringify({ timezone: tz }),
      }).catch(() => {});
    },
    [authFetch]
  );

  return { timezone, setTimezone };
}
