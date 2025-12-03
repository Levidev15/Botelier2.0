"use client";

import React from "react";
import { useParams, useRouter } from "next/navigation";
import { useState, useEffect } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { ArrowLeft, GitBranch } from "lucide-react";
import { useFlowStore } from "@/components/flow-editor/store";
import { useUnsavedChangesWarning } from "@/components/flow-editor/useUnsavedChangesWarning";
import { UnsavedChangesModal } from "@/components/flow-editor/UnsavedChangesModal";

const HOTEL_ID = "6b410bcc-f843-40df-b32d-078d3e01ac7f";

interface Tool {
  id: string;
  name: string;
  description: string;
  tool_type: string;
  config: any;
  hotel_id: string;
}

const FlowEditor = dynamic(
  () => import("@/components/flow-editor/FlowEditor").then((mod) => mod.default),
  {
    ssr: false,
    loading: () => (
      <div className="h-full flex items-center justify-center bg-[#0a0a0a]">
        <div className="text-center">
          <div className="animate-spin h-8 w-8 border-4 border-cyan-600 border-t-transparent rounded-full mx-auto" />
          <p className="mt-4 text-gray-400">Loading flow editor...</p>
        </div>
      </div>
    ),
  }
);

export default function FlowToolEditorPage() {
  const params = useParams();
  const router = useRouter();
  const toolId = params.id as string;
  const [tool, setTool] = useState<Tool | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  
  const isDirty = useFlowStore((state) => state.isDirty);
  const saveFlowFn = useFlowStore((state) => state.saveFlow);
  
  const handleSave = async () => {
    setIsSaving(true);
    try {
      await saveFlowFn();
    } finally {
      setIsSaving(false);
    }
  };
  
  const {
    showModal,
    handleNavigate,
    handleSaveAndNavigate,
    handleDiscardAndNavigate,
    handleCancelNavigation,
  } = useUnsavedChangesWarning({ isDirty, onSave: handleSave });

  const handleBackClick = (e: React.MouseEvent) => {
    e.preventDefault();
    if (!handleNavigate("/dashboard/tools")) {
      return;
    }
    router.push("/dashboard/tools");
  };

  useEffect(() => {
    const fetchTool = async () => {
      try {
        const response = await fetch(`/api/tools/${toolId}?hotel_id=${HOTEL_ID}`);
        if (!response.ok) {
          throw new Error("Tool not found");
        }
        const data = await response.json();
        
        if (data.tool_type !== "FLOW") {
          setError("This tool is not a conversation flow");
          return;
        }
        
        setTool(data);
      } catch (error) {
        console.error("Failed to fetch tool:", error);
        setError("Failed to load tool");
      } finally {
        setLoading(false);
      }
    };

    fetchTool();
  }, [toolId]);

  if (loading) {
    return (
      <div className="h-screen flex items-center justify-center bg-[#0a0a0a]">
        <div className="text-center">
          <div className="animate-spin h-8 w-8 border-4 border-cyan-600 border-t-transparent rounded-full mx-auto" />
          <p className="mt-4 text-gray-400">Loading...</p>
        </div>
      </div>
    );
  }

  if (error || !tool) {
    return (
      <div className="h-screen flex items-center justify-center bg-[#0a0a0a]">
        <div className="text-center">
          <p className="text-red-400 mb-4">{error || "Tool not found"}</p>
          <Link
            href="/dashboard/tools"
            className="text-cyan-400 hover:text-cyan-300 transition"
          >
            Back to Tools
          </Link>
        </div>
      </div>
    );
  }

  return (
    <>
    <div className="h-screen flex flex-col bg-[#0a0a0a]">
      <header className="h-14 border-b border-gray-800 flex items-center justify-between px-4 bg-[#141414]">
        <div className="flex items-center gap-4">
          <button
            onClick={handleBackClick}
            className="flex items-center gap-2 text-gray-400 hover:text-white transition"
          >
            <ArrowLeft className="h-4 w-4" />
            <span className="text-sm">Back to Tools</span>
          </button>
          
          <div className="h-6 w-px bg-gray-700" />
          
          <div className="flex items-center gap-2">
            <GitBranch className="h-5 w-5 text-cyan-500" />
            <span className="font-medium text-white">{tool.name}</span>
            <span className="text-gray-500 text-sm">/ Flow Editor</span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span className="px-2 py-1 text-xs bg-cyan-900/30 text-cyan-400 rounded">
            Conversation Flow
          </span>
        </div>
      </header>

      <main className="flex-1 overflow-hidden">
        <FlowEditor 
          toolId={toolId} 
          hotelId={HOTEL_ID}
          toolName={tool.name}
        />
      </main>
    </div>
    
    <UnsavedChangesModal
      isOpen={showModal}
      onSave={handleSaveAndNavigate}
      onDiscard={handleDiscardAndNavigate}
      onCancel={handleCancelNavigation}
      isSaving={isSaving}
    />
    </>
  );
}
