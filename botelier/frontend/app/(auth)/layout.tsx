import { SessionProvider } from "@/components/providers/SessionProvider";

export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <SessionProvider>{children}</SessionProvider>;
}
