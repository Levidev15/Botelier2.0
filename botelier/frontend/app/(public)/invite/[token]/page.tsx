"use client";

import { useSession, signIn } from "next-auth/react";
import { useRouter, useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuthToken } from "@/lib/auth/useAuthToken";

interface InvitationDetails {
  valid: boolean;
  invitation_id?: string;
  account_name?: string;
  role_name?: string;
  invitee_email?: string;
  expires_at?: string;
  error?: string;
}

export default function InvitePage() {
  const { data: session, status } = useSession();
  const { token: authToken, authFetch } = useAuthToken();
  const router = useRouter();
  const params = useParams();
  const inviteToken = params.token as string;

  const [invitation, setInvitation] = useState<InvitationDetails | null>(null);
  const [loading, setLoading] = useState(true);
  const [accepting, setAccepting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    if (inviteToken) {
      verifyInvitation();
    }
  }, [inviteToken]);

  const verifyInvitation = async () => {
    try {
      setLoading(true);
      const res = await fetch(`/api/invitations/verify/${inviteToken}`);
      const data = await res.json();
      setInvitation(data);
    } catch (err) {
      console.error("Error verifying invitation:", err);
      setInvitation({ valid: false, error: "Failed to verify invitation" });
    } finally {
      setLoading(false);
    }
  };

  const handleSignIn = async () => {
    await signIn("replit", { callbackUrl: `/invite/${inviteToken}` });
  };

  const handleAccept = async () => {
    if (!authToken) return;

    setAccepting(true);
    setError(null);

    try {
      const res = await authFetch("/api/invitations/accept", {
        method: "POST",
        body: JSON.stringify({ token: inviteToken }),
      });

      const data = await res.json();

      if (res.ok) {
        setSuccess(`Successfully joined ${data.account_name}!`);
        setTimeout(() => {
          router.push("/dashboard");
        }, 2000);
      } else {
        setError(data.detail || "Failed to accept invitation");
      }
    } catch (err) {
      console.error("Error accepting invitation:", err);
      setError("Failed to accept invitation");
    } finally {
      setAccepting(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-[#0a0a0a] flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin h-8 w-8 border-4 border-blue-600 border-t-transparent rounded-full mx-auto"></div>
          <p className="mt-4 text-gray-400">Verifying invitation...</p>
        </div>
      </div>
    );
  }

  if (!invitation || !invitation.valid) {
    return (
      <div className="min-h-screen bg-[#0a0a0a] flex items-center justify-center">
        <div className="max-w-md w-full px-6">
          <div className="bg-[#111111] border border-[#222222] rounded-xl p-8">
            <div className="text-center">
              <div className="w-16 h-16 bg-red-900/20 rounded-full flex items-center justify-center mx-auto mb-4">
                <svg className="w-8 h-8 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </div>
              <h1 className="text-xl font-bold text-white mb-2">Invalid Invitation</h1>
              <p className="text-gray-400 mb-6">
                {invitation?.error || "This invitation link is invalid or has expired."}
              </p>
              <button
                onClick={() => router.push("/login")}
                className="px-4 py-2 bg-[#222222] hover:bg-[#333333] text-white rounded-lg transition-colors"
              >
                Go to Login
              </button>
            </div>
          </div>
          <p className="mt-8 text-center text-gray-500 text-sm">
            Powered by Botelier AI Platform
          </p>
        </div>
      </div>
    );
  }

  if (success) {
    return (
      <div className="min-h-screen bg-[#0a0a0a] flex items-center justify-center">
        <div className="max-w-md w-full px-6">
          <div className="bg-[#111111] border border-[#222222] rounded-xl p-8">
            <div className="text-center">
              <div className="w-16 h-16 bg-green-900/20 rounded-full flex items-center justify-center mx-auto mb-4">
                <svg className="w-8 h-8 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
              </div>
              <h1 className="text-xl font-bold text-white mb-2">Welcome!</h1>
              <p className="text-gray-400 mb-4">{success}</p>
              <p className="text-gray-500 text-sm">Redirecting to dashboard...</p>
            </div>
          </div>
          <p className="mt-8 text-center text-gray-500 text-sm">
            Powered by Botelier AI Platform
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0a0a0a] flex items-center justify-center">
      <div className="max-w-md w-full px-6">
        <div className="bg-[#111111] border border-[#222222] rounded-xl p-8">
          <div className="text-center mb-6">
            <div className="w-16 h-16 bg-blue-900/20 rounded-full flex items-center justify-center mx-auto mb-4">
              <svg className="w-8 h-8 text-blue-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
              </svg>
            </div>
            <h1 className="text-2xl font-bold text-white mb-2">You're Invited!</h1>
            <p className="text-gray-400">
              You've been invited to join <span className="text-white font-medium">{invitation.account_name}</span>
            </p>
          </div>

          <div className="bg-[#0a0a0a] rounded-lg p-4 mb-6">
            <div className="flex justify-between items-center mb-2">
              <span className="text-gray-500">Account</span>
              <span className="text-white">{invitation.account_name}</span>
            </div>
            <div className="flex justify-between items-center mb-2">
              <span className="text-gray-500">Role</span>
              <span className="text-white">{invitation.role_name}</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-gray-500">Email</span>
              <span className="text-white">{invitation.invitee_email}</span>
            </div>
          </div>

          {error && (
            <div className="mb-4 p-4 bg-red-900/20 border border-red-900/50 rounded-lg">
              <p className="text-red-400 text-sm text-center">{error}</p>
            </div>
          )}

          {status === "authenticated" && authToken ? (
            <button
              onClick={handleAccept}
              disabled={accepting}
              className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-600/50 text-white font-medium rounded-lg transition-colors"
            >
              {accepting ? (
                <>
                  <div className="animate-spin h-5 w-5 border-2 border-white border-t-transparent rounded-full"></div>
                  <span>Accepting...</span>
                </>
              ) : (
                <>
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                  </svg>
                  <span>Accept Invitation</span>
                </>
              )}
            </button>
          ) : (
            <button
              onClick={handleSignIn}
              className="w-full flex items-center justify-center gap-3 px-4 py-3 bg-blue-600 hover:bg-blue-700 text-white font-medium rounded-lg transition-colors"
            >
              <svg
                className="w-5 h-5"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
                <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
              </svg>
              <span>Sign In to Accept</span>
            </button>
          )}

          <p className="mt-4 text-xs text-gray-500 text-center">
            By accepting, you agree to our Terms of Service and Privacy Policy.
          </p>
        </div>

        <p className="mt-8 text-center text-gray-500 text-sm">
          Powered by Botelier AI Platform
        </p>
      </div>
    </div>
  );
}
