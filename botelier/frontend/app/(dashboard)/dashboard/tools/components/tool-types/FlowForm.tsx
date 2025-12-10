"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { GitBranch } from "lucide-react";
import { notify } from "@/lib/notifications";

interface FlowFormProps {
  onSuccess: (tool: any) => void;
  onCancel: () => void;
  accountId: string;
}

interface FormData {
  name: string;
  description: string;
}

export default function FlowForm({ onSuccess, onCancel, accountId }: FlowFormProps) {
  const router = useRouter();
  const [formData, setFormData] = useState<FormData>({
    name: "",
    description: "",
  });

  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<Partial<FormData>>({});

  const validateForm = (): boolean => {
    const newErrors: Partial<FormData> = {};

    if (!formData.name.trim()) {
      newErrors.name = "Flow name is required";
    }

    if (!formData.description.trim()) {
      newErrors.description = "Description is required";
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!validateForm()) return;

    setSaving(true);

    try {
      const payload = {
        name: formData.name,
        description: formData.description,
        tool_type: "FLOW",
        config: {
          initial_node: null,
          nodes: [],
          edges: [],
        },
        hotel_id: accountId,
        is_active: true,
      };

      const response = await fetch("/api/tools", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        throw new Error("Failed to create flow");
      }

      const newTool = await response.json();
      notify.success("Flow created! Redirecting to flow editor...");
      onSuccess(newTool);
      
      setTimeout(() => {
        router.push(`/dashboard/tools/${newTool.id}/flow`);
      }, 500);
    } catch (error) {
      console.error("Error creating flow:", error);
      notify.error("Failed to create flow. Please try again.");
    } finally {
      setSaving(false);
    }
  };

  const handleChange = (field: keyof FormData, value: string) => {
    setFormData({ ...formData, [field]: value });
    if (errors[field]) {
      setErrors({ ...errors, [field]: undefined });
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <div className="flex items-center gap-3 pb-4 border-b border-gray-800">
        <div className="w-12 h-12 rounded-lg bg-cyan-600/20 flex items-center justify-center">
          <GitBranch className="text-cyan-500" size={24} />
        </div>
        <div>
          <h3 className="font-semibold">Conversation Flow</h3>
          <p className="text-sm text-gray-400">
            Design multi-step conversation workflows for your AI assistant
          </p>
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium mb-2">
          Flow Name <span className="text-red-500">*</span>
        </label>
        <input
          type="text"
          value={formData.name}
          onChange={(e) => handleChange("name", e.target.value)}
          placeholder="e.g., book_reservation"
          className={`w-full px-4 py-3 bg-[#141414] border ${
            errors.name ? "border-red-500" : "border-gray-800"
          } rounded-lg focus:outline-none focus:ring-2 focus:ring-cyan-600 focus:border-transparent`}
        />
        <p className="text-xs text-gray-500 mt-1">
          The AI will trigger this flow when a guest expresses the related intent
        </p>
        {errors.name && (
          <p className="text-xs text-red-500 mt-1">{errors.name}</p>
        )}
      </div>

      <div>
        <label className="block text-sm font-medium mb-2">
          Description <span className="text-red-500">*</span>
        </label>
        <textarea
          value={formData.description}
          onChange={(e) => handleChange("description", e.target.value)}
          placeholder="Describe when this flow should be triggered (e.g., 'When a guest wants to book a room or make a reservation')"
          rows={3}
          className={`w-full px-4 py-3 bg-[#141414] border ${
            errors.description ? "border-red-500" : "border-gray-800"
          } rounded-lg focus:outline-none focus:ring-2 focus:ring-cyan-600 focus:border-transparent resize-none`}
        />
        <p className="text-xs text-gray-500 mt-1">
          The AI uses this to detect when to start this conversation flow
        </p>
        {errors.description && (
          <p className="text-xs text-red-500 mt-1">{errors.description}</p>
        )}
      </div>

      <div className="bg-cyan-900/20 border border-cyan-800/30 rounded-lg p-4">
        <div className="flex items-start gap-3">
          <GitBranch className="text-cyan-500 mt-0.5" size={18} />
          <div>
            <p className="text-sm text-cyan-300 font-medium">Visual Flow Editor</p>
            <p className="text-xs text-gray-400 mt-1">
              After creating this flow, you&apos;ll be redirected to the visual flow editor where you can design the conversation steps using drag-and-drop nodes.
            </p>
          </div>
        </div>
      </div>

      <div className="flex gap-3 pt-4">
        <button
          type="button"
          onClick={onCancel}
          className="flex-1 px-6 py-3 bg-gray-800 hover:bg-gray-700 rounded-lg font-medium transition-colors"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={saving}
          className="flex-1 px-6 py-3 bg-cyan-600 hover:bg-cyan-700 rounded-lg font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {saving ? "Creating..." : "Create & Open Editor"}
        </button>
      </div>
    </form>
  );
}
