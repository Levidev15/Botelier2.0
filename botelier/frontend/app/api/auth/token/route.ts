import { getToken } from "next-auth/jwt";
import { NextRequest, NextResponse } from "next/server";
import { createHmac } from "node:crypto";

export const runtime = "nodejs";

// Never return the raw NextAuth identity token as a browser bearer. It must
// pass the backend's assurance/bootstrap boundary first.
export async function GET() {
  return NextResponse.json({ error: "Use the security sign-in exchange." }, { status: 405, headers: { Allow: "POST", "Cache-Control": "no-store" } });
}

export async function POST(request: NextRequest) {
  const origin = request.headers.get("origin");
  const publicOrigin = process.env.NEXTAUTH_URL ? new URL(process.env.NEXTAUTH_URL).origin : request.nextUrl.origin;
  if (request.headers.get("X-MFA-CSRF") !== "1" || (origin && origin !== publicOrigin && origin !== request.nextUrl.origin)) {
    return NextResponse.json({ error: "Invalid security request." }, { status: 403 });
  }
  const token = await getToken({ req: request, secret: process.env.NEXTAUTH_SECRET, raw: true });
  if (!token) return NextResponse.json({ error: "Please sign in with Replit again." }, { status: 401 });
  if (!process.env.NEXTAUTH_SECRET) return NextResponse.json({ error: "Sign-in service is not configured." }, { status: 503 });
  // Token-bound server attestation allows the backend to partition the trusted
  // exchange source rate limit by identity without accepting spoofable XFF.
  const exchangeAttestation = createHmac("sha256", process.env.NEXTAUTH_SECRET)
    .update(`botelier-mfa-exchange-v1\n${token}`)
    .digest("hex");
  // Preserve only the exact existing recovery-session cookie. The backend must
  // check it belongs to this identity before carrying any recovery grant over.
  // Never relay the browser's complete Cookie header or caller-supplied XFF.
  const mfaCookie = request.cookies.get("botelier_mfa_session")?.value;
  const recoveryCookie = mfaCookie && /^[A-Za-z0-9_-]{32,128}$/.test(mfaCookie)
    ? `botelier_mfa_session=${mfaCookie}` : undefined;
  try {
    const upstream = await fetch(`${process.env.BACKEND_URL || "http://localhost:3001"}/api/auth/mfa/bootstrap`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        "X-MFA-CSRF": "1",
        "X-Botelier-Auth-Exchange": exchangeAttestation,
        "Origin": publicOrigin,
        "X-Forwarded-Host": new URL(publicOrigin).host,
        "X-Forwarded-Proto": new URL(publicOrigin).protocol.replace(":", ""),
        ...(recoveryCookie ? { Cookie: recoveryCookie } : {}),
      },
      body: "{}",
      cache: "no-store",
    });
    const data = await upstream.json();
    const result = NextResponse.json(data, { status: upstream.status, headers: { "Cache-Control": "no-store" } });
    const cookies = upstream.headers.getSetCookie();
    for (const cookie of cookies) result.headers.append("Set-Cookie", cookie);
    return result;
  } catch {
    return NextResponse.json({ error: "Sign-in service unavailable. Please try again." }, { status: 502 });
  }
}
