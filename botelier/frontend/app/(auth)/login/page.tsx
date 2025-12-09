"use client";

import { signIn, useSession } from "next-auth/react";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

export default function LoginPage() {
  const { data: session, status } = useSession();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [isLoading, setIsLoading] = useState(false);
  const error = searchParams.get("error");
  const callbackUrl = searchParams.get("callbackUrl") || "/dashboard";

  useEffect(() => {
    if (status === "authenticated" && session) {
      router.push(callbackUrl);
    }
  }, [status, session, router, callbackUrl]);

  const handleSignIn = async () => {
    setIsLoading(true);
    try {
      await signIn("replit", { callbackUrl });
    } catch (err) {
      console.error("Sign in error:", err);
      setIsLoading(false);
    }
  };

  if (status === "loading") {
    return (
      <div className="min-h-screen bg-[#0a0a0a] flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin h-8 w-8 border-4 border-blue-600 border-t-transparent rounded-full mx-auto"></div>
          <p className="mt-4 text-gray-400">Loading...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0a0a0a] flex items-center justify-center">
      <div className="max-w-md w-full px-6">
        <div className="bg-[#111111] border border-[#222222] rounded-xl p-8">
          <div className="text-center mb-8">
            <h1 className="text-2xl font-bold text-white mb-2">
              Welcome to Botelier
            </h1>
            <p className="text-gray-400">
              Sign in to manage your voice AI assistants
            </p>
          </div>

          {error && (
            <div className="mb-6 p-4 bg-red-900/20 border border-red-900/50 rounded-lg">
              <p className="text-red-400 text-sm text-center">
                {error === "OAuthSignin"
                  ? "Error starting sign in. Please try again."
                  : error === "OAuthCallback"
                  ? "Error during sign in callback. Please try again."
                  : error === "OAuthAccountNotLinked"
                  ? "This email is already linked to another account."
                  : "An error occurred during sign in. Please try again."}
              </p>
            </div>
          )}

          <button
            onClick={handleSignIn}
            disabled={isLoading}
            className="w-full flex items-center justify-center gap-3 px-4 py-3 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-600/50 text-white font-medium rounded-lg transition-colors"
          >
            {isLoading ? (
              <>
                <div className="animate-spin h-5 w-5 border-2 border-white border-t-transparent rounded-full"></div>
                <span>Signing in...</span>
              </>
            ) : (
              <>
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
                <span>Sign In</span>
              </>
            )}
          </button>

          <p className="mt-6 text-xs text-gray-500 text-center">
            By signing in, you agree to our Terms of Service and Privacy Policy.
          </p>
        </div>

        <p className="mt-8 text-center text-gray-500 text-sm">
          Powered by Botelier AI Platform
        </p>
      </div>
    </div>
  );
}
