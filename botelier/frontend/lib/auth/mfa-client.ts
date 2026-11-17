"use client";

export interface AuthUser {
  id: string;
  email: string;
  user_type: string;
  auth_provider?: string;
  [key: string]: unknown;
}

export interface AuthResult {
  access_token?: string | null;
  user?: AuthUser;
  mfa_required?: boolean;
  enrollment_required?: boolean;
  recovery_codes?: string[];
}

export interface MfaStatus {
  user: AuthUser;
  mfa_enabled: boolean;
  mfa_required: boolean;
  enrollment_required: boolean;
  policy_required: boolean;
  primary_fresh: boolean;
  mfa_fresh: boolean;
  recovery_codes_remaining: number;
  recovery_session_reference?: string | null;
}

export class MfaError extends Error {
  constructor(message: string, public code: string, public status: number) {
    super(message);
  }
}

export function storedAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  try { return localStorage.getItem("botelier_token"); } catch { return null; }
}

export function safeReturnPath(value: string | null, fallback = "/dashboard"): string {
  // Reject protocol-relative URLs, backslashes, and auth loops.
  if (!value || !value.startsWith("/") || value.startsWith("//") || /[\\\r\n]/.test(value)) return fallback;
  if (/^\/(?:login|security|api\/auth)(?:[/?#]|$)/.test(value)) return fallback;
  return value;
}

export function clearAuthStorage() {
  localStorage.removeItem("botelier_token");
  localStorage.removeItem("botelier_user");
  window.dispatchEvent(new Event("botelier-auth-changed"));
}

export function clearAccountStorage() {
  localStorage.removeItem("botelier_account_context");
  for (const key of Object.keys(localStorage)) {
    if (key.startsWith("botelier_perm_cache_")) localStorage.removeItem(key);
  }
}

export function acceptAuthResult(result: AuthResult): boolean {
  // A pending challenge is represented ONLY by the HttpOnly backend cookie.
  if (!result.access_token || result.mfa_required || result.enrollment_required) {
    clearAuthStorage();
    return false;
  }
  localStorage.setItem("botelier_token", result.access_token);
  if (result.user) localStorage.setItem("botelier_user", JSON.stringify(result.user));
  window.dispatchEvent(new Event("botelier-auth-changed"));
  return true;
}

export async function mfaRequest<T>(path: string, body?: unknown, method?: string): Promise<T> {
  const token = storedAccessToken();
  const response = await fetch(`/api/auth/mfa${path}`, {
    method: method || (body === undefined ? "GET" : "POST"),
    credentials: "same-origin",
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      "X-MFA-CSRF": "1",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data.detail;
    throw new MfaError(
      typeof detail === "string" ? detail : detail?.message || "Security request failed. Please try again.",
      detail?.code || "", response.status,
    );
  }
  return data as T;
}

export async function redirectForMfa(response: Response): Promise<boolean> {
  if (response.status !== 403) return false;
  const data = await response.clone().json().catch(() => ({}));
  const code = data.detail?.code;
  if (!["mfa_required", "mfa_verification_required", "primary_auth_required", "mfa_enrollment_required"].includes(code)) return false;
  if (window.location.pathname !== "/security") {
    const next = safeReturnPath(window.location.pathname + window.location.search);
    window.location.assign(`/security?next=${encodeURIComponent(next)}`);
  }
  return true;
}

export async function endMfaSession(): Promise<void> {
  try {
    await mfaRequest("/logout", {});
  } catch (err) {
    // A definitive auth denial means this credential is already unusable.
    // Still clear local/NextAuth state, but never hide transport/5xx/CSRF errors.
    if (err instanceof MfaError && (err.status === 401 ||
        (err.status === 403 && ["session_expired", "session_revoked"].includes(err.code)))) return;
    throw err;
  }
}
