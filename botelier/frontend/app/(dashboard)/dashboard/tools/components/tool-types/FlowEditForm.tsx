"use client";

import { useState, useEffect } from "react";
import { GitBranch } from "lucide-react";
import { notify } from "@/lib/notifications";
import { useAuthToken } from "@/lib/auth/useAuthToken";

interface Tool {
  id: string;
  name: string;
  description: string;
  tool_type: string;
  config: any;
  is_active: boolean;
}

interface FlowEditFormProps {
  tool: Tool;
  onSuccess: (tool: any) => void;
  onCancel: () => void;
  toolSetId?: string;
}

interface FormData {
  name: string;
  description: string;
}

export default function FlowEditForm({ tool, onSuccess, onCancel, toolSetId }: FlowEditFormProps) {
  const { authFetch } = useAuthToken();
  const [formData, setFormData] = useState<FormData>({
    name: tool.name,
    description: tool.description,
  });
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<Partial<FormData>>({});

  useEffect(() => {
    setFormData({ name: tool.name, description: tool.description });
    setErrors({});
  }, [tool]);

  const validate = (): boolean => {
    const newErrors: Partial<FormData> = {};
    if (!formData.name.trim()) newErrors.name = "Name is required";
    if (!formData.description.trim()) newErrors.description = "Description is required";
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validate()) return;
    setSaving(true);
    try {
      const scopeParam = toolSetId ? `tool_set_id=${toolSetId}` : "";
      const response = await authFetch(`/api/tools/${tool.id}${scopeParam ? `?${scopeParam}` : ""}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: formData.name.trim(),
          description: formData.description.trim(),
        }),
      });

      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to update flow");
      }

      const updated = await response.json();
      notify.success("Flow updated");
      onSuccess(updated);
    } catch (error: any) {
      notify.error(error.message || "Failed to update flow");
    } finally {
      setSaving(false);
    }
  };

  const handleChange = (field: keyof FormData, value: string) => {
    setFormData({ ...formData, [field]: value });
    if (errors[field]) setErrors({ ...errors, [field]: undefined });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <div className="flex items-center gap-3 pb-4 border-b border-gray-800">
        <div className="w-12 h-12 rounded-lg bg-cyan-600/20 flex items-center justify-center">
          <GitBranch className="text-cyan-500" size={24} />
        </div>
        <div>
          <h3 className="font-semibold">Edit Flow</h3>
          <p className="text-sm text-gray-400">Update the name and description of this flow</p>
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
          Letters, digits, spaces, hyphens, and underscores only
        </p>
        {errors.name && <p className="text-xs text-red-500 mt-1">{errors.name}</p>}
      </div>

      <div>
        <label className="block text-sm font-medium mb-2">
          Description <span className="text-red-500">*</span>
        </label>
        <textarea
          value={formData.description}
          onChange={(e) => handleChange("description", e.target.value)}
          placeholder="Describe when this flow should be triggered"
          rows={3}
          className={`w-full px-4 py-3 bg-[#141414] border ${
            errors.description ? "border-red-500" : "border-gray-800"
          } rounded-lg focus:outline-none focus:ring-2 focus:ring-cyan-600 focus:border-transparent resize-none`}
        />
        {errors.description && <p className="text-xs text-red-500 mt-1">{errors.description}</p>}
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
          {saving ? "Saving..." : "Save Changes"}
        </button>
      </div>
    </form>
  );
}
