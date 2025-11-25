"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowLeft, Bot } from "lucide-react";
import Link from "next/link";
import dynamic from "next/dynamic";

const FlowEditor = dynamic(
  () => import("@/components/flow-editor/FlowEditor").then((mod) => mod.default),
  {
    ssr: false,
    loading: () => (
      <div className="h-full flex items-center justify-center bg-[#0a0a0a]">
        <div className="text-center">
          <div className="animate-spin h-8 w-8 border-4 border-blue-600 border-t-transparent rounded-full mx-auto" />
          <p className="mt-4 text-gray-400">Loading flow editor...</p>
        </div>
      </div>
    ),
  }
);

interface Assistant {
  id: string;
  name: string;
  hotel_id: string;
}

export default function FlowEditorPage() {
  const params = useParams();
  const router = useRouter();
  const assistantId = params.id as string;
  const [assistant, setAssistant] = useState<Assistant | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchAssistant = async () => {
      try {
        const response = await fetch(`/api/assistants/${assistantId}`);
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
            <span className="text-gray-500 text-sm">/ Flow Editor</span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Link
            href={`/dashboard/assistants/${assistantId}`}
            className="px-3 py-1.5 text-sm text-gray-400 hover:text-white transition"
          >
            Settings
          </Link>
          <div className="px-3 py-1.5 text-sm text-blue-400 border-b-2 border-blue-500">
            Flow
          </div>
        </div>
      </header>

      <main className="flex-1 overflow-hidden">
        <FlowEditor 
          assistantId={assistantId} 
          assistantName={assistant.name}
        />
      </main>
    </div>
  );
}
