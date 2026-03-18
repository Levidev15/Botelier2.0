"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowLeft, Bot, GitBranch, ArrowRight } from "lucide-react";
import Link from "next/link";
import { useAuthToken } from "@/lib/auth/useAuthToken";

interface Assistant {
  id: string;
  name: string;
  hotel_id: string;
}

export default function FlowEditorPage() {
  const params = useParams();
  const router = useRouter();
  const assistantId = params.id as string;
  const { authFetch } = useAuthToken();
  const [assistant, setAssistant] = useState<Assistant | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchAssistant = async () => {
      try {
        const response = await authFetch(`/api/assistants/${assistantId}`);
        if (!response.ok) {
          throw new Error("Assistant not found");
        }
        const data = await response.json();
        setAssistant(data);
      } catch (error) {
        console.error("Failed to fetch assistant:", error);
        router.push("/dashboard/assistants");
      } finally {
        setLoading(false);
      }
    };

    fetchAssistant();
  }, [assistantId, router]);

  if (loading) {
    return (
      <div className="h-screen flex items-center justify-center bg-[#0a0a0a]">
        <div className="text-center">
          <div className="animate-spin h-8 w-8 border-4 border-blue-600 border-t-transparent rounded-full mx-auto" />
          <p className="mt-4 text-gray-400">Loading...</p>
        </div>
      </div>
    );
  }

  if (!assistant) {
    return null;
  }

  return (
    <div className="h-screen flex flex-col bg-[#0a0a0a]">
      <header className="h-14 border-b border-gray-800 flex items-center justify-between px-4 bg-[#141414]">
        <div className="flex items-center gap-4">
          <Link
            href={`/dashboard/assistants/${assistantId}`}
            className="flex items-center gap-2 text-gray-400 hover:text-white transition"
          >
            <ArrowLeft className="h-4 w-4" />
            <span className="text-sm">Back to Assistant</span>
          </Link>
          
          <div className="h-6 w-px bg-gray-700" />
          
          <div className="flex items-center gap-2">
            <Bot className="h-5 w-5 text-blue-500" />
            <span className="font-medium text-white">{assistant.name}</span>
            <span className="text-gray-500 text-sm">/ Flow</span>
          </div>
        </div>
      </header>

      <main className="flex-1 flex items-center justify-center p-8">
        <div className="max-w-md text-center">
          <div className="w-16 h-16 mx-auto mb-6 rounded-full bg-cyan-900/30 flex items-center justify-center">
            <GitBranch className="w-8 h-8 text-cyan-500" />
          </div>
          
          <h1 className="text-2xl font-bold text-white mb-3">
            Flows Have Moved to Tools
          </h1>
          
          <p className="text-gray-400 mb-6">
            Conversation flows are now managed as reusable tools that your AI assistant can trigger based on guest intent. This allows you to share flows across multiple assistants and create more natural conversations.
          </p>
          
          <Link
            href="/dashboard/tools"
            className="inline-flex items-center gap-2 px-6 py-3 bg-cyan-600 hover:bg-cyan-700 text-white rounded-lg font-medium transition-colors"
          >
            Go to Tools
            <ArrowRight className="w-4 h-4" />
          </Link>
          
          <p className="text-xs text-gray-500 mt-6">
            Create a new &quot;Conversation Flow&quot; tool to design your flow
          </p>
        </div>
      </main>
    </div>
  );
}
