import { NextAuthOptions } from "next-auth";

export const authOptions: NextAuthOptions = {
  providers: [
    {
      id: "replit",
      name: "Replit",
      type: "oauth",
      wellKnown: "https://replit.com/.well-known/openid-configuration",
      clientId: process.env.REPL_ID!,
      clientSecret: "",
      authorization: {
        params: {
          scope: "openid email profile offline_access",
          prompt: "login consent",
          max_age: 0,
        },
      },
      checks: ["pkce"],
      idToken: true,
      profile(profile) {
        return {
          id: profile.sub,
          name: profile.first_name
            ? `${profile.first_name} ${profile.last_name || ""}`.trim()
            : profile.email?.split("@")[0] || `User ${profile.sub}`,
          email: profile.email,
          image: profile.profile_image_url,
          replitId: profile.sub,
          // This timestamp comes from the validated provider response and is
          // captured only on sign-in, never from NextAuth's rolling JWT iat.
          authTime: typeof profile.auth_time === "number" ? profile.auth_time : undefined,
        };
      },
    },
  ],
  callbacks: {
    async jwt({ token, user, account }) {
      if (account && user) {
        token.accessToken = account.access_token;
        token.refreshToken = account.refresh_token;
        token.replitId = (user as any).replitId || user.id;
        // A successful interactive provider callback is primary authentication.
        token.auth_time = (user as any).authTime ?? Math.floor(Date.now() / 1000);
      }
      return token;
    },
    async session({ session, token }) {
      return {
        ...session,
        accessToken: token.accessToken,
        user: {
          ...session.user,
          id: token.replitId as string,
          replitId: token.replitId as string,
        },
      };
    },
  },
  pages: {
    signIn: "/login",
    error: "/login",
  },
  session: {
    strategy: "jwt",
    maxAge: 30 * 24 * 60 * 60,
  },
  secret: process.env.NEXTAUTH_SECRET,
};
