"use client";

import { useEffect, useRef, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { useAuthToken } from "@/lib/auth/useAuthToken";
import { CheckCircle, AlertCircle, Loader2 } from "lucide-react";

/**
 * OAuth2 completion page.
 *
 * Reached via the GET /oauth/callback hop on the API host, which 302s here
 * after the provider redirects the browser back with code + state.
 *
 * This page:
 *   1. Reads code, state, and optional error from the URL query string.
 *   2. Makes an authenticated POST to /api/integrations/oauth/complete using
 *      the user's existing Bearer token (authFetch).
 *   3. Shows a spinner → success or error state.
 *   4. Redirects to /dashboard/integrations after a short pause.
 *
 * Security: the backend endpoint requires a valid Bearer token, so only the
 * authenticated user who initiated the flow (or another user in the same
 * account) can complete the exchange.  A forwarded callback link fails
 * without a valid session.
 */
export default function OAuthCompletePage() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const { authFetch, loading: authLoading, isAuthenticated } = useAuthToken();

  const [status, setStatus] = useState<"pending" | "success" | "error">("pending");
  const [message, setMessage] = useState("");

  // Guard against running the completion twice in React strict-mode double-invocations.
  const completedRef = useRef(false);

  useEffect(() => {
    if (authLoading) return;

    if (!isAuthenticated) {
      // Not logged in — redirect to login, preserving this URL as callbackUrl.
      router.replace(`/login?callbackUrl=${encodeURIComponent(window.location.href)}`);
      return;
    }

    if (completedRef.current) return;
    completedRef.current = true;

    const code = searchParams.get("code");
    const state = searchParams.get("state");
    const error = searchParams.get("error");

    complete(code, state, error);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authLoading, isAuthenticated]);

  async function complete(
    code: string | null,
    state: string | null,
    error: string | null,
  ) {
    try {
      const resp = await authFetch("/api/integrations/oauth/complete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code, state, error }),
      });

      if (resp.ok) {
        const data = await resp.json();
        const name = data.integration_name || data.integration_slug || "Integration";
        const slug: string = data.integration_slug || "";
        setStatus("success");
        setMessage(`${name} connected successfully`);

        // Email sender connections belong in Settings > Email, not in the
        // general Integrations page.
        const isEmailSender = slug.startsWith("email-sender-");
        setTimeout(() => {
          if (isEmailSender) {
            router.replace("/dashboard/settings?tab=email&connected=1");
          } else {
            router.replace(
              `/dashboard/integrations?integration_connected=${encodeURIComponent(slug)}`,
            );
          }
        }, 2000);
      } else {
        const data = await resp.json().catch(() => ({}));
        const detail: string = data.detail || "Connection failed";
        setStatus("error");
        setMessage(detail);
        setTimeout(() => {
          router.replace(
            `/dashboard/integrations?integration_error=${encodeURIComponent(detail)}`,
          );
        }, 3000);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "An unexpected error occurred";
      setStatus("error");
      setMessage(msg);
      setTimeout(() => {
        router.replace("/dashboard/integrations?integration_error=network_error");
      }, 3000);
    }
  }

  return (
    <div className="flex items-center justify-center min-h-screen bg-background">
      <div className="text-center space-y-4 px-6 max-w-sm">
        {status === "pending" && (
          <>
            <Loader2 className="h-12 w-12 animate-spin mx-auto text-blue-500" />
            <p className="text-lg font-medium">Completing OAuth connection…</p>
            <p className="text-sm text-muted-foreground">
              Please wait while we exchange the authorization code.
            </p>
          </>
        )}

        {status === "success" && (
          <>
            <CheckCircle className="h-12 w-12 mx-auto text-green-500" />
            <p className="text-lg font-semibold">{message}</p>
            <p className="text-sm text-muted-foreground">
              Redirecting to integrations…
            </p>
          </>
        )}

        {status === "error" && (
          <>
            <AlertCircle className="h-12 w-12 mx-auto text-red-500" />
            <p className="text-lg font-semibold">Connection failed</p>
            <p className="text-sm text-muted-foreground">{message}</p>
            <p className="text-sm text-muted-foreground mt-2">
              Redirecting back to integrations…
            </p>
          </>
        )}
      </div>
    </div>
  );
}
