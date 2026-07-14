"use client";

import { useState, useEffect } from "react";
import { Sparkles, Loader2 } from "lucide-react";
import { notify } from "@/lib/notifications";
import { useAuthToken } from "@/lib/auth/useAuthToken";

interface Tool {
  id: string;
  name: string;
  description: string;
  tool_type: string;
  config: {
    capability?: string;
  };
  is_active: boolean;
}

interface CapabilityFormProps {
  onSuccess: (tool: any) => void;
  onCancel: () => void;
  tool?: Tool;
  accountId: string;
  toolSetId?: string;
}

interface CapabilityParam {
  type?: string;
  description?: string;
}

interface Capability {
  name: string;
  description: string;
  parameters: Record<string, CapabilityParam>;
  required: string[];
  mutating: boolean;
  service_backed: boolean;
}

interface FormData {
  name: string;
  description: string;
  capability: string;
}

interface FormErrors {
  name?: string;
  description?: string;
  capability?: string;
}

function prettify(name: string): string {
  return name
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

export default function CapabilityForm({ onSuccess, onCancel, tool, accountId, toolSetId }: CapabilityFormProps) {
  const isEditMode = !!tool;
  const { authFetch } = useAuthToken();

  const [formData, setFormData] = useState<FormData>({
    name: "",
    description: "",
    capability: "",
  });
  const [capabilities, setCapabilities] = useState<Capability[]>([]);
  const [loadingCapabilities, setLoadingCapabilities] = useState(false);
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<FormErrors>({});

  useEffect(() => {
    const fetchCapabilities = async () => {
      setLoadingCapabilities(true);
      try {
        const response = await authFetch("/api/capabilities");
        if (response.ok) {
          const resData = await response.json();
          setCapabilities(Array.isArray(resData) ? resData : []);
        }
      } catch {
        notify.error("Failed to load capabilities");
      } finally {
        setLoadingCapabilities(false);
      }
    };
    fetchCapabilities();
  }, [authFetch]);

  useEffect(() => {
    if (tool) {
      setFormData({
        name: tool.name || "",
        description: tool.description || "",
        capability: tool.config?.capability || "",
      });
    }
  }, [tool]);

  const selected = capabilities.find((c) => c.name === formData.capability);

  const validateForm = (): boolean => {
    const newErrors: FormErrors = {};
    if (!formData.name.trim()) {
      newErrors.name = "Tool name is required";
    }
    if (!formData.description.trim()) {
      newErrors.description = "Description is required";
    }
    if (!formData.capability) {
      newErrors.capability = "Select a capability";
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
        tool_type: "CAPABILITY",
        config: {
          capability: formData.capability,
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
        <div className="w-12 h-12 rounded-lg bg-purple-600/20 flex items-center justify-center">
          <Sparkles className="text-purple-400" size={24} />
        </div>
        <div>
          <h3 className="font-semibold">{isEditMode ? "Edit" : "Create"} Capability Tool</h3>
          <p className="text-sm text-gray-400">
            A vendor-neutral action that resolves to your connected provider at runtime
          </p>
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium mb-2">
          Capability <span className="text-red-500">*</span>
        </label>
        {loadingCapabilities ? (
          <div className="flex items-center gap-2 text-sm text-gray-500 py-2">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading capabilities...
          </div>
        ) : (
          <select
            value={formData.capability}
            onChange={(e) => handleChange("capability", e.target.value)}
            className={`w-full px-4 py-3 bg-[#141414] border ${
              errors.capability ? "border-red-500" : "border-gray-800"
            } rounded-lg focus:outline-none focus:ring-2 focus:ring-purple-600 focus:border-transparent`}
          >
            <option value="">Select a capability...</option>
            {capabilities.map((c) => (
              <option key={c.name} value={c.name}>
                {prettify(c.name)}
              </option>
            ))}
          </select>
        )}
        {errors.capability && (
          <p className="text-xs text-red-500 mt-1">{errors.capability}</p>
        )}
        {selected && (
          <div className="mt-2 rounded-lg border border-gray-800 bg-[#141414] p-3 space-y-2">
            <p className="text-xs text-gray-400">{selected.description}</p>
            <div className="flex flex-wrap gap-1">
              {selected.mutating && (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-900/40 text-amber-400 font-medium">
                  Write action
                </span>
              )}
              {selected.service_backed && (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-900/40 text-blue-400 font-medium">
                  Managed service
                </span>
              )}
            </div>
            {Object.keys(selected.parameters).length > 0 && (
              <ul className="space-y-1">
                {Object.entries(selected.parameters).map(([key, param]) => (
                  <li key={key} className="text-xs text-gray-400">
                    <span className="font-mono text-purple-300">{key}</span>
                    {selected.required.includes(key) && (
                      <span className="text-red-500 ml-1">*</span>
                    )}
                    {param.description && (
                      <span className="text-gray-500"> — {param.description}</span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>

      <div>
        <label className="block text-sm font-medium mb-2">
          Tool Name <span className="text-red-500">*</span>
        </label>
        <input
          type="text"
          value={formData.name}
          onChange={(e) => handleChange("name", e.target.value)}
          placeholder="e.g., check_room_availability"
          className={`w-full px-4 py-3 bg-[#141414] border ${
            errors.name ? "border-red-500" : "border-gray-800"
          } rounded-lg focus:outline-none focus:ring-2 focus:ring-purple-600 focus:border-transparent`}
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
          placeholder="e.g., Use when the caller wants to know what rooms are available for their dates"
          rows={3}
          className={`w-full px-4 py-3 bg-[#141414] border ${
            errors.description ? "border-red-500" : "border-gray-800"
          } rounded-lg focus:outline-none focus:ring-2 focus:ring-purple-600 focus:border-transparent resize-none`}
        />
        {errors.description && (
          <p className="text-xs text-red-500 mt-1">{errors.description}</p>
        )}
      </div>

      <div className="flex gap-3 pt-2">
        <button
          type="submit"
          disabled={saving}
          className="flex-1 px-4 py-3 bg-purple-600 hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg transition-colors font-medium"
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
