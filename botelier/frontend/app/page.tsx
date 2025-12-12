"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

export default function Home() {
  const router = useRouter();
  const [isChecking, setIsChecking] = useState(true);

  useEffect(() => {
    const storedToken = localStorage.getItem("botelier_token");
    const storedUser = localStorage.getItem("botelier_user");
    
    if (storedToken && storedUser) {
      try {
        const user = JSON.parse(storedUser);
        if (user?.user_type === "platform_admin") {
          router.replace("/admin");
        } else {
          router.replace("/dashboard/assistants");
        }
      } catch {
        router.replace("/login");
      }
    } else {
      router.replace("/login");
    }
    
    setIsChecking(false);
  }, [router]);

  if (!isChecking) return null;

  return (
    <div className="min-h-screen bg-[#0a0a0a] flex items-center justify-center">
      <div className="flex flex-col items-center gap-6">
        <div className="relative">
          <div className="w-14 h-14 rounded-xl bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center">
            <span className="text-xl font-bold text-white">B</span>
          </div>
          <div className="absolute inset-0 rounded-xl bg-gradient-to-br from-blue-500/30 to-purple-600/30 blur-lg animate-pulse" />
        </div>
        <div className="flex items-center gap-1">
          <div className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-bounce" style={{ animationDelay: "0ms" }} />
          <div className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-bounce" style={{ animationDelay: "150ms" }} />
          <div className="w-1.5 h-1.5 rounded-full bg-purple-500 animate-bounce" style={{ animationDelay: "300ms" }} />
        </div>
      </div>
    </div>
  );
}
