"use client";

import { useState, useEffect } from "react";
import { PhoneOff } from "lucide-react";
import { notify } from "@/lib/notifications";
import { useAuthToken } from "@/lib/auth/useAuthToken";

interface Tool {
  id: string;
  name: string;
  description: string;
  tool_type: string;
  config: {
    goodbye_message?: string;
  };
  is_active: boolean;
}

interface EndCallFormProps {
  onSuccess: (tool: any) => void;
  onCancel: () => void;
  tool?: Tool;
  accountId: string;
  toolSetId?: string;
}

interface FormData {
  name: string;
  description: string;
  goodbye_message: string;
}

interface FormErrors {
  name?: string;
  description?: string;
}

const DEFAULT_GOODBYE = "Thank you for calling. Have a great day, goodbye!";
const DEFAULT_DESCRIPTION =
  "End the call when the caller confirms they don't need anything else, says goodbye, or their question has been fully answered.";

export default function EndCallForm({ onSuccess, onCancel, tool, accountId, toolSetId }: EndCallFormProps) {
  const isEditMode = !!tool;
  const { authFetch } = useAuthToken();

  const [formData, setFormData] = useState<FormData>({
    name: "",
    description: DEFAULT_DESCRIPTION,
    goodbye_message: DEFAULT_GOODBYE,
  });

  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<FormErrors>({});

  useEffect(() => {
    if (tool) {
      setFormData({
        name: tool.name || "",
        description: tool.description || DEFAULT_DESCRIPTION,
        goodbye_message: tool.config?.goodbye_message || DEFAULT_GOODBYE,
      });
    }
  }, [tool]);

  const validateForm = (): boolean => {
    const newErrors: FormErrors = {};
    if (!formData.name.trim()) {
      newErrors.name = "Tool name is required";
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
        name: formData.name.trim(),
        description: formData.description.trim(),
        tool_type: "END_CALL",
        config: {
          goodbye_message: formData.goodbye_message.trim() || DEFAULT_GOODBYE,
        },
        tool_set_id: toolSetId,
        is_active: true,
      };

      const scopeParam = toolSetId ? `tool_set_id=${toolSetId}` : `account_id=${accountId}`;
      const url = isEditMode
        ? `/api/tools/${tool!.id}?${scopeParam}`
        : "/api/tools";
      const method = isEditMode ? "PUT" : "POST";

      const response = await authFetch(url, {
        method,
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        const errorData = await response.json();
        let errorMsg = `Failed to ${isEditMode ? "update" : "create"} tool`;
        if (typeof errorData.detail === "string") {
          errorMsg = errorData.detail;
        } else if (Array.isArray(errorData.detail)) {
          errorMsg = errorData.detail.map((e: any) => e.msg || e.message || JSON.stringify(e)).join(", ");
        }
        throw new Error(errorMsg);
      }

      const savedTool = await response.json();
      notify.success(`Tool ${isEditMode ? "updated" : "created"} successfully`);
      onSuccess(savedTool);
    } catch (error) {
      console.error(`Error ${isEditMode ? "updating" : "creating"} tool:`, error);
      notify.error(error instanceof Error ? error.message : `Failed to ${isEditMode ? "update" : "create"} tool. Please try again.`);
    } finally {
      setSaving(false);
    }
  };

  const handleChange = <K extends keyof FormData>(field: K, value: FormData[K]) => {
    setFormData({ ...formData, [field]: value });
    if (errors[field as keyof FormErrors]) {
      setErrors({ ...errors, [field]: undefined });
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <div className="flex items-center gap-3 pb-4 border-b border-gray-800">
        <div className="w-12 h-12 rounded-lg bg-red-600/20 flex items-center justify-center">
          <PhoneOff className="text-red-500" size={24} />
        </div>
        <div>
          <h3 className="font-semibold">{isEditMode ? "Edit" : "Create"} End Call Tool</h3>
          <p className="text-sm text-gray-400">
            Let the bot end the call after successfully helping the caller
          </p>
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium mb-2">
          Tool Name <span className="text-red-500">*</span>
        </label>
        <input
          type="text"
          value={formData.name}
          onChange={(e) => handleChange("name", e.target.value)}
          placeholder="e.g., end_conversation"
          className={`w-full px-4 py-3 bg-[#141414] border ${
            errors.name ? "border-red-500" : "border-gray-800"
          } rounded-lg focus:outline-none focus:ring-2 focus:ring-red-600 focus:border-transparent`}
        />
        <p className="text-xs text-gray-500 mt-1">
          Used internally by the AI (lowercase, underscores)
        </p>
        {errors.name && (
          <p className="text-xs text-red-500 mt-1">{errors.name}</p>
        )}
      </div>

      <div>
        <label className="block text-sm font-medium mb-2">
          When should the bot use this? <span className="text-red-500">*</span>
        </label>
        <textarea
          value={formData.description}
          onChange={(e) => handleChange("description", e.target.value)}
          placeholder="e.g., End the call when the caller confirms they don't need anything else or says goodbye"
          rows={3}
          className={`w-full px-4 py-3 bg-[#141414] border ${
            errors.description ? "border-red-500" : "border-gray-800"
          } rounded-lg focus:outline-none focus:ring-2 focus:ring-red-600 focus:border-transparent resize-none`}
        />
        <p className="text-xs text-gray-500 mt-1">
          The AI reads this to decide when to end the call — be specific about the trigger (e.g., "caller says that's all", "question fully answered and caller is satisfied")
        </p>
        {errors.description && (
          <p className="text-xs text-red-500 mt-1">{errors.description}</p>
        )}
      </div>

      <div>
        <label className="block text-sm font-medium mb-2">
          Goodbye Message
        </label>
        <textarea
          value={formData.goodbye_message}
          onChange={(e) => handleChange("goodbye_message", e.target.value)}
          placeholder={DEFAULT_GOODBYE}
          rows={2}
          className="w-full px-4 py-3 bg-[#141414] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-red-600 focus:border-transparent resize-none"
        />
        <p className="text-xs text-gray-500 mt-1">
          What the bot says before hanging up. Keep it natural and warm.
        </p>
      </div>

      <div className="flex gap-3 pt-2">
        <button
          type="submit"
          disabled={saving}
          className="flex-1 px-4 py-3 bg-red-600 hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg transition-colors font-medium"
        >
          {saving ? (isEditMode ? "Saving..." : "Creating...") : (isEditMode ? "Save Changes" : "Create Tool")}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="px-4 py-3 bg-gray-800 hover:bg-gray-700 text-white rounded-lg transition-colors"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
