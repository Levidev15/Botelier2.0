"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ShieldCheck, Loader2 } from "lucide-react";
import { MfaError, mfaRequest } from "@/lib/auth/mfa-client";

export function MfaPolicyCard({ accountId, canEdit }: { accountId: string; canEdit: boolean }) {
  const [enabled, setEnabled] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [needsVerification, setNeedsVerification] = useState(false);
  const [saved, setSaved] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true); setLoaded(false); setError(""); setSaved(false);
    mfaRequest<{ require_mfa: boolean }>(`/policy/${encodeURIComponent(accountId)}`)
      .then(data => { if (!cancelled) { setEnabled(data.require_mfa); setLoaded(true); } })
      .catch(err => { if (!cancelled) setError(err instanceof Error ? err.message : "Unable to load MFA policy."); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [accountId]);

  async function changePolicy() {
    const target = !enabled;
    if (!window.confirm(target
      ? "Require MFA for this account? All active members must enroll and verify before their next access. This requirement applies to their Botelier sign-in across accounts."
      : "Remove this account's MFA requirement? Enrolled authenticators remain enabled, and administrator or other account requirements still apply.")) return;
    setSaving(true); setError(""); setSaved(false); setNeedsVerification(false);
    try {
      const data = await mfaRequest<{ require_mfa: boolean }>(`/policy/${encodeURIComponent(accountId)}`, { require_mfa: target }, "PATCH");
      setEnabled(data.require_mfa); setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to update MFA policy.");
      if (err instanceof MfaError && ["primary_auth_required", "mfa_verification_required", "mfa_required", "mfa_enrollment_required"].includes(err.code)) setNeedsVerification(true);
    } finally { setSaving(false); }
  }

  return (
    <section className="rounded-lg border border-gray-800 bg-[#141414] p-6 space-y-4">
      <div className="flex items-center gap-3"><ShieldCheck className="text-blue-400" size={20} /><h2 className="text-lg font-semibold">Account sign-in security</h2></div>
      <p className="text-sm text-gray-400">Require every active account member to use an authenticator app. Membership in a required account makes MFA mandatory across their Botelier sign-in. Platform administrators always require MFA.</p>
      {loading ? <Loader2 aria-label="Loading MFA policy" className="animate-spin text-blue-400" size={18} /> : loaded && (
        <div className="flex flex-wrap items-center justify-between gap-4">
          <span className="text-sm">MFA requirement: <strong>{enabled ? "Required" : "Optional"}</strong></span>
          {canEdit && <button type="button" disabled={saving} onClick={changePolicy} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium hover:bg-blue-700 disabled:opacity-50">{saving ? "Saving…" : enabled ? "Remove requirement" : "Require MFA"}</button>}
        </div>
      )}
      {error && <p role="alert" className="text-sm text-red-400">{error}</p>}
      {saved && <p role="status" className="text-sm text-green-400">MFA policy updated.</p>}
      {canEdit && <p className="text-xs text-gray-400">Changes require a recent primary sign-in and authenticator verification. Enroll yourself before enabling this policy.</p>}
      <Link className="inline-block text-sm text-blue-400 hover:text-blue-300" href="/security?next=%2Fdashboard%2Fsettings">{needsVerification ? "Verify your identity to continue →" : "Manage your personal security →"}</Link>
    </section>
  );
}
