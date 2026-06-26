import type { Metadata } from "next";
import { Inter, Cormorant_Garamond, Syne, DM_Sans } from "next/font/google";
import { Toaster } from "sonner";
import { ThemeProvider } from "@/lib/theme/ThemeContext";
import { SessionProvider } from "@/components/providers/SessionProvider";
import "./globals.css";

const inter = Inter({ subsets: ["latin"] });

const cormorant = Cormorant_Garamond({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  variable: "--font-cormorant",
  display: "swap",
});

const syne = Syne({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700", "800"],
  variable: "--font-syne",
  display: "swap",
});

const dmSans = DM_Sans({
  subsets: ["latin"],
  style: ["normal", "italic"],
  variable: "--font-dm-sans",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Botelier - Voice AI Platform",
  description: "Manage your voice AI assistants",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      data-theme="dark"
      suppressHydrationWarning
      className={`${cormorant.variable} ${syne.variable} ${dmSans.variable}`}
    >
      <body className={inter.className}>
        <SessionProvider>
          <ThemeProvider>
            {children}
            <Toaster position="top-right" richColors closeButton />
          </ThemeProvider>
        </SessionProvider>
      </body>
    </html>
  );
}
