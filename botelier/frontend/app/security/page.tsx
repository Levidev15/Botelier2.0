"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { signIn, signOut } from "next-auth/react";
import Link from "next/link";
import { ShieldCheck, KeyRound, Download, Loader2, ArrowLeft, LogOut } from "lucide-react";
import {
  acceptAuthResult, AuthResult, clearAccountStorage, clearAuthStorage, endMfaSession, MfaError, mfaRequest, MfaStatus, safeReturnPath, storedAccessToken,
} from "@/lib/auth/mfa-client";

const inputClass = "mt-2 w-full rounded-lg border border-border bg-background px-3 py-3 text-foreground focus:outline-none focus:ring-2 focus:ring-blue-500";
const buttonClass = "inline-flex items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed";

function SecurityScreen() {
  const params = useSearchParams();
  const [status, setStatus] = useState<MfaStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [recovery, setRecovery] = useState(false);
  const [enrollment, setEnrollment] = useState<{ secret: string; qr_data_url: string } | null>(null);
  const [codes, setCodes] = useState<string[]>([]);
  const [savedCodes, setSavedCodes] = useState(false);
  const [needsLogin, setNeedsLogin] = useState(false);
  const [needsRecoveryOperator, setNeedsRecoveryOperator] = useState(false);
  const initialized = useRef(false);
  const next = safeReturnPath(params.get("next"), status?.user.user_type === "platform_admin" ? "/admin" : "/dashboard");
  // A consumed recovery code may leave mfa_enabled set for policy purposes,
  // but enrollment_required means the previous factor is no longer usable.
  const activeAuthenticator = !!status?.mfa_enabled && !status?.enrollment_required;

  const refresh = useCallback(async () => {
    const updated = await mfaRequest<MfaStatus>("/status");
    setStatus(updated);
    return updated;
  }, []);

  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;
    (async () => {
      try {
        // On an explicit Replit callback, exchange the signed identity on the
        // server. Do not expose its raw NextAuth token to browser storage.
        if (params.get("replit") === "1") {
          const response = await fetch("/api/auth/token", {
            method: "POST", credentials: "same-origin", headers: { "X-MFA-CSRF": "1" }, cache: "no-store",
          });
          const data = await response.json();
          if (!response.ok) throw new MfaError(data.detail?.message || data.error || "Please sign in again.", data.detail?.code || "", response.status);
          if ("access_token" in data) acceptAuthResult(data);
          else clearAuthStorage();
          await refresh();
        } else {
          try { await refresh(); } catch (err) {
            if (!storedAccessToken()) throw err;
            const bootstrapped = await mfaRequest<MfaStatus & AuthResult>("/bootstrap", {});
            if ("access_token" in bootstrapped) acceptAuthResult(bootstrapped);
            setStatus(bootstrapped);
          }
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Unable to load security settings.");
        setNeedsLogin(true);
      } finally { setLoading(false); }
    })();
  }, [params, refresh]);

  async function action(work: () => Promise<void>) {
    setError(""); setNotice(""); setBusy(true);
    try { await work(); } catch (err) {
      setError(err instanceof Error ? err.message : "Security request failed.");
      if (err instanceof MfaError) {
        if (err.status === 401) setNeedsLogin(true);
        if (err.code === "recovery_session_required") setNeedsRecoveryOperator(true);
        if (err.code === "primary_auth_required") {
          setEnrollment(null);
          setStatus(s => s ? { ...s, primary_fresh: false } : s);
        }
        if (err.code === "enrollment_expired") setEnrollment(null);
        if (err.code === "mfa_verification_required") setStatus(s => s ? { ...s, mfa_fresh: false } : s);
      }
    } finally { setBusy(false); setCode(""); setPassword(""); }
  }

  async function handleAuthResult(result: AuthResult) {
    acceptAuthResult(result);
    if (result.recovery_codes) {
      setCodes(result.recovery_codes); setSavedCodes(false);
    }
    setEnrollment(null);
    setNeedsRecoveryOperator(false);
    await refresh();
  }

  async function logout() {
    await action(async () => {
      await endMfaSession();
      clearAuthStorage();
      clearAccountStorage();
      await signOut({ redirect: false });
      window.location.assign("/login");
    });
  }

  function downloadCodes() {
    const blob = new Blob([`Botelier recovery codes\nKeep these private. Each code works once.\n\n${codes.join("\n")}\n`], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url; link.download = "botelier-recovery-codes.txt"; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  if (loading) return <main className="min-h-screen bg-background flex items-center justify-center"><Loader2 aria-label="Loading security settings" className="animate-spin text-blue-500" /></main>;

  return (
    <main className="themed-app min-h-screen bg-background text-foreground px-4 py-10 sm:py-16">
      <div className="mx-auto max-w-2xl">
        <header className="mb-8 flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-3"><ShieldCheck className="h-8 w-8 text-blue-500" /><h1 className="text-2xl font-semibold">Account security</h1></div>
            <p className="mt-3 text-sm text-muted-foreground">Protect your Botelier sign-in with an authenticator app.</p>
            {status && <p className="mt-2 text-sm text-muted-foreground">{status.user.email}</p>}
          </div>
          {!needsLogin && <button onClick={logout} disabled={busy} className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"><LogOut size={16} />Sign out</button>}
        </header>

        {error && <div role="alert" className="mb-5 rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-400">{error}</div>}
        {notice && <div role="status" className="mb-5 rounded-lg border border-green-500/30 bg-green-500/10 p-4 text-sm text-green-400">{notice}</div>}

        {needsLogin ? (
          <section className="rounded-xl border border-border bg-surface p-6 space-y-4">
            <h2 className="text-lg font-semibold">Sign in to continue</h2>
            <p className="text-sm text-muted-foreground">Your security session expired or needs a fresh sign-in. Your authenticator settings have not changed.</p>
            <Link className={buttonClass} href={`/login?reauth=1&callbackUrl=${encodeURIComponent("/security")}`}>Sign in again</Link>
            <button className="block text-sm text-blue-400" onClick={() => signIn("replit", { callbackUrl: "/security?replit=1" })}>Continue with Replit</button>
          </section>
        ) : status && (
          <>
            {status.policy_required && <div className="mb-5 rounded-lg border border-blue-500/30 bg-blue-500/10 p-4 text-sm text-blue-300">MFA is required by your administrator role or an account you belong to. Complete verification before accessing Botelier.</div>}

            {needsRecoveryOperator && status.recovery_session_reference && (
              <section className="mb-5 rounded-xl border border-amber-500/30 bg-surface p-6 space-y-3">
                <h2 className="text-lg font-semibold">Verified recovery assistance</h2>
                <p className="text-sm text-muted-foreground">Stay in this browser. During a verified live support interaction, your security operator can use this noncredential reference to identify this exact recovery session. Email alone cannot authorize recovery.</p>
                <p className="text-xs text-muted-foreground">Recovery session reference</p>
                <code className="block break-all rounded-lg bg-background p-3 text-sm select-all">{status.recovery_session_reference}</code>
                <p className="text-xs text-muted-foreground">Share only this reference with your verified security operator. Never share your password, cookie, bearer token, setup key, or recovery codes. After the operator confirms approval, try authenticator setup again before the grant expires.</p>
              </section>
            )}

            {codes.length > 0 ? (
              <section className="rounded-xl border border-border bg-surface p-6 space-y-5">
                <h2 className="text-lg font-semibold">Save your recovery codes</h2>
                <p className="text-sm text-muted-foreground">These ten codes are shown only once. Store them somewhere safe outside this device. Using a code will require setting up a new authenticator.</p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 rounded-lg bg-background p-4 font-mono text-sm select-all">{codes.map(c => <span key={c}>{c}</span>)}</div>
                <button type="button" onClick={downloadCodes} className={buttonClass}><Download size={16} />Download recovery codes</button>
                <label className="flex gap-3 text-sm"><input type="checkbox" checked={savedCodes} onChange={e => setSavedCodes(e.target.checked)} />I have saved these codes in a safe place.</label>
                <button disabled={!savedCodes} onClick={() => { setCodes([]); window.location.assign(next); }} className={buttonClass}>Continue to Botelier</button>
              </section>
            ) : (
              <div className="space-y-5">
                {!status.primary_fresh && (
                  <section className="rounded-xl border border-border bg-surface p-6">
                    <h2 className="text-lg font-semibold">Confirm your identity</h2>
                    <p className="mt-2 text-sm text-muted-foreground">A recent sign-in is needed before changing security settings.</p>
                    <form className="mt-4 space-y-4" onSubmit={e => { e.preventDefault(); action(async () => {
                      const result = await mfaRequest<MfaStatus & AuthResult>("/reauthenticate", { password });
                      if ("access_token" in result) acceptAuthResult(result);
                      setStatus(result);
                      setNotice("Identity confirmed.");
                    }); }}>
                      <label className="block text-sm">Current password<input type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} className={inputClass} required /></label>
                      <button disabled={busy || !password} className={buttonClass}>Confirm password</button>
                    </form>
                    <button className="mt-4 text-sm text-blue-400" onClick={() => signIn("replit", { callbackUrl: "/security?replit=1" })}>Use Replit sign-in instead</button>
                  </section>
                )}

                {activeAuthenticator && !status.mfa_fresh && !enrollment && (
                  <section className="rounded-xl border border-border bg-surface p-6">
                    <h2 className="text-lg font-semibold">{recovery ? "Use a recovery code" : "Verify your authenticator"}</h2>
                    <p className="mt-2 text-sm text-muted-foreground">{recovery ? "Enter one unused recovery code. Your lost authenticator will be revoked and you will set up a replacement." : "Enter the six-digit code from Microsoft Authenticator, Google Authenticator, or your compatible app."}</p>
                    <form className="mt-4 space-y-4" onSubmit={e => { e.preventDefault(); action(async () => { await handleAuthResult(await mfaRequest<AuthResult>("/verify", { code })); setNotice(recovery ? "Recovery accepted. Set up your new authenticator below." : "Authenticator verified."); }); }}>
                      <label className="block text-sm">{recovery ? "Recovery code" : "Authenticator code"}<input autoComplete="one-time-code" inputMode={recovery ? "text" : "numeric"} pattern={recovery ? undefined : "[0-9]{6}"} maxLength={recovery ? 100 : 6} value={code} onChange={e => setCode(e.target.value)} className={inputClass} required /></label>
                      <button disabled={busy || !code} className={buttonClass}>{busy && <Loader2 size={16} className="animate-spin" />}Verify</button>
                    </form>
                    <button type="button" className="mt-4 text-sm text-blue-400" onClick={() => { setRecovery(!recovery); setCode(""); }}>{recovery ? "Use an authenticator code instead" : "Lost your phone? Use a recovery code"}</button>
                  </section>
                )}

                {enrollment ? (
                  <section className="rounded-xl border border-border bg-surface p-6 space-y-5">
                    <h2 className="text-lg font-semibold">Connect your authenticator</h2>
                    <ol className="list-decimal pl-5 space-y-2 text-sm text-muted-foreground"><li>Open Microsoft Authenticator, Google Authenticator, or another TOTP app.</li><li>Add an account and scan this QR code, or enter the setup key manually.</li><li>Enter a generated code below to activate protection.</li></ol>
                    {enrollment.qr_data_url.startsWith("data:image/") && <img src={enrollment.qr_data_url} alt="Authenticator enrollment QR code — keep private" className="h-52 w-52 rounded-lg bg-white p-3" />}
                    <div><p className="text-xs text-muted-foreground">Manual setup key (keep private)</p><code className="mt-2 block break-all rounded-lg bg-background p-3 select-all">{enrollment.secret}</code></div>
                    <form className="space-y-4" onSubmit={e => { e.preventDefault(); action(async () => { await handleAuthResult(await mfaRequest<AuthResult>("/confirm", { code })); }); }}>
                      <label className="block text-sm">Six-digit code<input inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} value={code} onChange={e => setCode(e.target.value)} className={inputClass} required /></label>
                      <button disabled={busy || code.length !== 6} className={buttonClass}>Activate authenticator</button>
                    </form>
                  </section>
                ) : (
                  <section className="rounded-xl border border-border bg-surface p-6 space-y-4">
                    <div className="flex items-center justify-between gap-3"><h2 className="text-lg font-semibold">Authenticator app</h2><span className={`text-xs rounded-full px-3 py-1 ${activeAuthenticator ? "bg-green-500/10 text-green-400" : "bg-amber-500/10 text-amber-400"}`}>{activeAuthenticator ? "Enabled" : "Not enrolled"}</span></div>
                    <p className="text-sm text-muted-foreground">Authenticator codes add a second check after your existing login. No Google or Microsoft account connection is required.</p>
                    <button disabled={busy || !status.primary_fresh || (activeAuthenticator && !status.mfa_fresh)} className={buttonClass} onClick={() => action(async () => {
                      if (activeAuthenticator && !window.confirm("Replace your authenticator? After confirmation, the old authenticator, recovery codes, and other sessions will be revoked.")) return;
                      setEnrollment(await mfaRequest("/enroll", {}));
                      setNeedsRecoveryOperator(false);
                    })}><KeyRound size={16} />{activeAuthenticator ? "Replace authenticator" : "Set up authenticator"}</button>
                    {activeAuthenticator && (
                      <div className="border-t border-border pt-4 space-y-3">
                        <p className="text-sm text-muted-foreground">{status.recovery_codes_remaining} recovery codes remaining.</p>
                        <button className="block text-sm text-blue-400 disabled:opacity-40" disabled={busy || !status.primary_fresh || !status.mfa_fresh} onClick={() => action(async () => {
                          if (!window.confirm("Generate new recovery codes? Previous codes and other sessions will stop working.")) return;
                          await handleAuthResult(await mfaRequest<AuthResult>("/recovery-codes", {}));
                        })}>Generate new recovery codes</button>
                        {status.policy_required ? <p className="text-xs text-muted-foreground">MFA cannot be disabled while your administrator role or an account requires it.</p> :
                          <button className="block text-sm text-red-400 disabled:opacity-40" disabled={busy || !status.primary_fresh || !status.mfa_fresh} onClick={() => action(async () => {
                            if (!window.confirm("Disable MFA? Your account will no longer have authenticator protection.")) return;
                            await handleAuthResult(await mfaRequest<AuthResult>("/disable", {})); setNotice("Authenticator disabled.");
                          })}>Disable authenticator</button>}
                      </div>
                    )}
                  </section>
                )}
                {!status.mfa_required && !status.enrollment_required && <Link href={next} className="inline-flex items-center gap-2 text-sm text-blue-400"><ArrowLeft size={16} />Continue to Botelier</Link>}
                <p className="text-xs text-muted-foreground">Never share setup keys or recovery codes. If you lose both your phone and recovery codes, contact your administrator for the verified recovery process. We cannot reset MFA by email alone.</p>
              </div>
            )}
          </>
        )}
      </div>
    </main>
  );
}

export default function SecurityPage() {
  return <Suspense fallback={<div className="p-8">Loading security settings…</div>}><SecurityScreen /></Suspense>;
}
