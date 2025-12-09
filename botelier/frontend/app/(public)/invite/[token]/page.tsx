"use client";

import { useRouter, useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Eye, EyeOff, CheckCircle, XCircle, Mail, User, Lock } from "lucide-react";

interface InvitationDetails {
  valid: boolean;
  email?: string;
  account_name?: string;
  role_name?: string;
  expires_at?: string;
  error?: string;
}

export default function InvitePage() {
  const router = useRouter();
  const params = useParams();
  const inviteToken = params.token as string;

  const [invitation, setInvitation] = useState<InvitationDetails | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);

  const passwordMinLength = 8;
  const passwordHasUppercase = /[A-Z]/.test(password);
  const passwordHasLowercase = /[a-z]/.test(password);
  const passwordHasNumber = /[0-9]/.test(password);
  const passwordsMatch = password === confirmPassword && password.length > 0;
  const isPasswordValid = password.length >= passwordMinLength && passwordHasUppercase && passwordHasLowercase && passwordHasNumber;
  const isFormValid = firstName.trim() && lastName.trim() && isPasswordValid && passwordsMatch;

  useEffect(() => {
    if (inviteToken) {
      verifyInvitation();
    }
  }, [inviteToken]);

  const verifyInvitation = async () => {
    try {
      setLoading(true);
      const res = await fetch(`/api/auth/verify-invitation/${inviteToken}`);
      const data = await res.json();
      setInvitation(data);
    } catch (err) {
      console.error("Error verifying invitation:", err);
      setInvitation({ valid: false, error: "Failed to verify invitation" });
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!isFormValid || !invitation?.email) return;

    setSubmitting(true);
    setError(null);

    try {
      const res = await fetch("/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: invitation.email,
          password: password,
          first_name: firstName,
          last_name: lastName,
          invitation_token: inviteToken,
        }),
      });

      const data = await res.json();

      if (res.ok) {
        localStorage.setItem("botelier_token", data.access_token);
        localStorage.setItem("botelier_user", JSON.stringify(data.user));
        
        setSuccess(`Welcome to ${invitation.account_name}!`);
        setTimeout(() => {
          router.push(data.redirect_url || "/dashboard");
        }, 2000);
      } else {
        setError(data.detail || "Failed to create account");
      }
    } catch (err) {
      console.error("Error creating account:", err);
      setError("Failed to create account. Please try again.");
    } finally {
      setSubmitting(false);
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
                <XCircle className="w-8 h-8 text-red-500" />
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
                <CheckCircle className="w-8 h-8 text-green-500" />
              </div>
              <h1 className="text-xl font-bold text-white mb-2">Account Created!</h1>
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
    <div className="min-h-screen bg-[#0a0a0a] flex items-center justify-center py-12">
      <div className="max-w-md w-full px-6">
        <div className="bg-[#111111] border border-[#222222] rounded-xl p-8">
          <div className="text-center mb-6">
            <div className="w-16 h-16 bg-blue-900/20 rounded-full flex items-center justify-center mx-auto mb-4">
              <Mail className="w-8 h-8 text-blue-500" />
            </div>
            <h1 className="text-2xl font-bold text-white mb-2">You're Invited!</h1>
            <p className="text-gray-400">
              Join <span className="text-white font-medium">{invitation.account_name}</span> as {invitation.role_name}
            </p>
          </div>

          <div className="bg-[#0a0a0a] rounded-lg p-4 mb-6">
            <div className="flex items-center gap-3">
              <Mail className="w-4 h-4 text-gray-500" />
              <span className="text-white">{invitation.email}</span>
            </div>
          </div>

          {error && (
            <div className="mb-4 p-4 bg-red-900/20 border border-red-900/50 rounded-lg">
              <p className="text-red-400 text-sm text-center">{error}</p>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-400 mb-1">
                  First Name
                </label>
                <div className="relative">
                  <User className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
                  <input
                    type="text"
                    value={firstName}
                    onChange={(e) => setFirstName(e.target.value)}
                    required
                    className="w-full pl-10 pr-3 py-2 bg-[#0a0a0a] border border-[#333333] rounded-lg text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
                    placeholder="John"
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-400 mb-1">
                  Last Name
                </label>
                <div className="relative">
                  <User className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
                  <input
                    type="text"
                    value={lastName}
                    onChange={(e) => setLastName(e.target.value)}
                    required
                    className="w-full pl-10 pr-3 py-2 bg-[#0a0a0a] border border-[#333333] rounded-lg text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
                    placeholder="Doe"
                  />
                </div>
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-400 mb-1">
                Create Password
              </label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
                <input
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  minLength={8}
                  className="w-full pl-10 pr-10 py-2 bg-[#0a0a0a] border border-[#333333] rounded-lg text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
                  placeholder="Min. 8 characters"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300"
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
              {password.length > 0 && (
                <div className="mt-2 space-y-1">
                  <div className="flex items-center gap-2 text-xs">
                    {password.length >= passwordMinLength ? (
                      <CheckCircle className="w-3 h-3 text-green-500" />
                    ) : (
                      <XCircle className="w-3 h-3 text-gray-500" />
                    )}
                    <span className={password.length >= passwordMinLength ? "text-green-400" : "text-gray-500"}>
                      At least 8 characters
                    </span>
                  </div>
                  <div className="flex items-center gap-2 text-xs">
                    {passwordHasUppercase && passwordHasLowercase ? (
                      <CheckCircle className="w-3 h-3 text-green-500" />
                    ) : (
                      <XCircle className="w-3 h-3 text-gray-500" />
                    )}
                    <span className={passwordHasUppercase && passwordHasLowercase ? "text-green-400" : "text-gray-500"}>
                      Upper and lowercase letters
                    </span>
                  </div>
                  <div className="flex items-center gap-2 text-xs">
                    {passwordHasNumber ? (
                      <CheckCircle className="w-3 h-3 text-green-500" />
                    ) : (
                      <XCircle className="w-3 h-3 text-gray-500" />
                    )}
                    <span className={passwordHasNumber ? "text-green-400" : "text-gray-500"}>
                      At least one number
                    </span>
                  </div>
                </div>
              )}
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-400 mb-1">
                Confirm Password
              </label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
                <input
                  type={showConfirmPassword ? "text" : "password"}
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  required
                  className="w-full pl-10 pr-10 py-2 bg-[#0a0a0a] border border-[#333333] rounded-lg text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
                  placeholder="Confirm your password"
                />
                <button
                  type="button"
                  onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300"
                >
                  {showConfirmPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
              {confirmPassword.length > 0 && (
                <div className="mt-2 flex items-center gap-2 text-xs">
                  {passwordsMatch ? (
                    <>
                      <CheckCircle className="w-3 h-3 text-green-500" />
                      <span className="text-green-400">Passwords match</span>
                    </>
                  ) : (
                    <>
                      <XCircle className="w-3 h-3 text-red-500" />
                      <span className="text-red-400">Passwords do not match</span>
                    </>
                  )}
                </div>
              )}
            </div>

            <button
              type="submit"
              disabled={!isFormValid || submitting}
              className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-600/50 disabled:cursor-not-allowed text-white font-medium rounded-lg transition-colors mt-6"
            >
              {submitting ? (
                <>
                  <div className="animate-spin h-5 w-5 border-2 border-white border-t-transparent rounded-full"></div>
                  <span>Creating Account...</span>
                </>
              ) : (
                <span>Create Account & Join</span>
              )}
            </button>
          </form>

          <p className="mt-4 text-xs text-gray-500 text-center">
            By creating an account, you agree to our Terms of Service and Privacy Policy.
          </p>

          <div className="mt-6 pt-6 border-t border-[#222222] text-center">
            <p className="text-gray-400 text-sm">
              Already have an account?{" "}
              <button
                onClick={() => router.push("/login")}
                className="text-blue-400 hover:text-blue-300"
              >
                Sign In
              </button>
            </p>
          </div>
        </div>

        <p className="mt-8 text-center text-gray-500 text-sm">
          Powered by Botelier AI Platform
        </p>
      </div>
    </div>
  );
}
