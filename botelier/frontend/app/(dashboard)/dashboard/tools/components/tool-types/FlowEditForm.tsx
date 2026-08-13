"use client";

import { useState, useEffect } from "react";
import { GitBranch, ChevronDown } from "lucide-react";
import { notify } from "@/lib/notifications";
import { useAuthToken } from "@/lib/auth/useAuthToken";

interface Tool {
  id: string;
  name: string;
  description: string;
  tool_type: string;
  config: any;
  is_active: boolean;
  llm_provider?: string | null;
  llm_model?: string | null;
  llm_temperature?: number | null;
  llm_max_tokens?: number | null;
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
  llm_provider: string;
  llm_model: string;
  llm_temperature: string;
  llm_max_tokens: string;
}

interface LLMProvider {
  id: string;
  display_name: string;
  default_model: string;
  models: { value: string; label: string }[];
}

export default function FlowEditForm({ tool, onSuccess, onCancel, toolSetId }: FlowEditFormProps) {
  const { authFetch } = useAuthToken();
  const [formData, setFormData] = useState<FormData>({
    name: tool.name,
    description: tool.description,
    llm_provider: tool.llm_provider ?? "",
    llm_model: tool.llm_model ?? "",
    llm_temperature: tool.llm_temperature != null ? String(tool.llm_temperature) : "",
    llm_max_tokens: tool.llm_max_tokens != null ? String(tool.llm_max_tokens) : "",
  });
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<Partial<Record<keyof FormData, string>>>({});
  const [providers, setProviders] = useState<Record<string, LLMProvider>>({});
  const [loadingProviders, setLoadingProviders] = useState(true);

  // Load providers once on mount
  useEffect(() => {
    authFetch("/api/providers/llm")
      .then((r) => r.json())
      .then((data) => setProviders(data.providers ?? {}))
      .catch(() => {/* non-fatal — form still works without provider list */})
      .finally(() => setLoadingProviders(false));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    setFormData({
      name: tool.name,
      description: tool.description,
      llm_provider: tool.llm_provider ?? "",
      llm_model: tool.llm_model ?? "",
      llm_temperature: tool.llm_temperature != null ? String(tool.llm_temperature) : "",
      llm_max_tokens: tool.llm_max_tokens != null ? String(tool.llm_max_tokens) : "",
    });
    setErrors({});
  }, [tool]);

  const validate = (): boolean => {
    const newErrors: Partial<Record<keyof FormData, string>> = {};
    if (!formData.name.trim()) newErrors.name = "Name is required";
    if (!formData.description.trim()) newErrors.description = "Description is required";
    if (formData.llm_temperature !== "") {
      const t = parseFloat(formData.llm_temperature);
      if (isNaN(t) || t < 0 || t > 2) newErrors.llm_temperature = "Must be between 0 and 2";
    }
    if (formData.llm_max_tokens !== "") {
      const n = parseInt(formData.llm_max_tokens, 10);
      if (isNaN(n) || n < 1 || n > 32768) newErrors.llm_max_tokens = "Must be between 1 and 32768";
    }
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validate()) return;
    setSaving(true);
    try {
      const scopeParam = toolSetId ? `tool_set_id=${toolSetId}` : "";
      const payload: Record<string, any> = {
        name: formData.name.trim(),
        description: formData.description.trim(),
        // Send null to clear a previously set value; omit the key entirely when
        // the field was never touched (handled via undefined check below).
        llm_provider: formData.llm_provider || null,
        llm_model: formData.llm_model || null,
        llm_temperature: formData.llm_temperature !== "" ? parseFloat(formData.llm_temperature) : null,
        llm_max_tokens: formData.llm_max_tokens !== "" ? parseInt(formData.llm_max_tokens, 10) : null,
      };

      const response = await authFetch(
        `/api/tools/${tool.id}${scopeParam ? `?${scopeParam}` : ""}`,
        { method: "PATCH", body: JSON.stringify(payload) }
      );

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
    setFormData((prev) => ({ ...prev, [field]: value }));
    if (errors[field]) setErrors((prev) => ({ ...prev, [field]: undefined }));
  };

  // When the provider changes, pick the provider's default model automatically.
  const handleProviderChange = (value: string) => {
    const defaultModel = value ? (providers[value]?.default_model ?? "") : "";
    setFormData((prev) => ({ ...prev, llm_provider: value, llm_model: defaultModel }));
  };

  const currentModels = formData.llm_provider ? (providers[formData.llm_provider]?.models ?? []) : [];
  const tempValue = formData.llm_temperature !== "" ? parseFloat(formData.llm_temperature) : null;

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3 pb-4 border-b border-gray-800">
        <div className="w-12 h-12 rounded-lg bg-cyan-600/20 flex items-center justify-center">
          <GitBranch className="text-cyan-500" size={24} />
        </div>
        <div>
          <h3 className="font-semibold">Edit Flow</h3>
          <p className="text-sm text-gray-400">Update the name, description, and LLM settings for this flow</p>
        </div>
      </div>

      {/* Name */}
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

      {/* Description */}
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

      {/* LLM Settings section */}
      <div className="border border-gray-800 rounded-lg overflow-hidden">
        <div className="px-4 py-3 bg-[#141414] border-b border-gray-800">
          <h4 className="text-sm font-semibold">LLM Settings</h4>
          <p className="text-xs text-gray-400 mt-0.5">
            Override the assistant&rsquo;s default AI model for this flow. Leave blank to use the assistant&rsquo;s settings.
          </p>
        </div>

        <div className="p-4 space-y-5">
          {/* Provider */}
          <div>
            <label className="block text-xs font-medium text-gray-400 mb-1.5">Provider</label>
            <div className="relative">
              <select
                value={formData.llm_provider}
                onChange={(e) => handleProviderChange(e.target.value)}
                disabled={loadingProviders}
                className="w-full px-3 py-2.5 bg-[#141414] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-cyan-600 text-sm appearance-none pr-8 disabled:opacity-50"
              >
                <option value="">— Use assistant default —</option>
                {Object.entries(providers).map(([key, p]) => (
                  <option key={key} value={key}>{p.display_name}</option>
                ))}
              </select>
              <ChevronDown size={14} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
            </div>
          </div>

          {/* Model */}
          <div>
            <label className="block text-xs font-medium text-gray-400 mb-1.5">Model</label>
            <div className="relative">
              <select
                value={formData.llm_model}
                onChange={(e) => handleChange("llm_model", e.target.value)}
                disabled={!formData.llm_provider || currentModels.length === 0}
                className="w-full px-3 py-2.5 bg-[#141414] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-cyan-600 text-sm appearance-none pr-8 disabled:opacity-50"
              >
                {currentModels.length === 0 ? (
                  <option value="">— Select a provider first —</option>
                ) : (
                  currentModels.map((m) => (
                    <option key={m.value} value={m.value}>{m.label}</option>
                  ))
                )}
              </select>
              <ChevronDown size={14} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
            </div>
          </div>

          {/* Temperature */}
          <div>
            <label className="block text-xs font-medium text-gray-400 mb-1.5">
              Temperature{tempValue != null && <span className="ml-1 text-white font-semibold">{tempValue.toFixed(2)}</span>}
            </label>
            <input
              type="range"
              min={0}
              max={2}
              step={0.05}
              value={tempValue ?? 0.4}
              onChange={(e) => handleChange("llm_temperature", e.target.value)}
              className="w-full accent-cyan-500"
            />
            <div className="flex justify-between text-xs text-gray-500 mt-1">
              <span>Strict (0)</span>
              <span>Balanced (0.5 – 1)</span>
              <span>Creative (2)</span>
            </div>
            <div className="flex justify-between items-center mt-2">
              <p className="text-xs text-gray-500">
                Lower = follows instructions precisely. Higher = more creative / unpredictable.
                <br />
                Recommended for booking flows: <span className="text-cyan-400">0.3 – 0.5</span>
              </p>
              <button
                type="button"
                onClick={() => handleChange("llm_temperature", "")}
                className="text-xs text-gray-500 hover:text-gray-300 ml-4 shrink-0"
              >
                Use default
              </button>
            </div>
            {errors.llm_temperature && (
              <p className="text-xs text-red-500 mt-1">{errors.llm_temperature}</p>
            )}
          </div>

          {/* Max output tokens */}
          <div>
            <label className="block text-xs font-medium text-gray-400 mb-1.5">Max Output Tokens</label>
            <input
              type="number"
              min={1}
              max={32768}
              step={50}
              value={formData.llm_max_tokens}
              onChange={(e) => handleChange("llm_max_tokens", e.target.value)}
              placeholder="Leave blank to use assistant default (400)"
              className={`w-full px-3 py-2.5 bg-[#141414] border ${
                errors.llm_max_tokens ? "border-red-500" : "border-gray-800"
              } rounded-lg focus:outline-none focus:ring-2 focus:ring-cyan-600 text-sm`}
            />
            <p className="text-xs text-gray-500 mt-1">
              Maximum words the AI can say per reply. 400 covers most responses; increase for detailed confirmations.
            </p>
            {errors.llm_max_tokens && (
              <p className="text-xs text-red-500 mt-1">{errors.llm_max_tokens}</p>
            )}
          </div>
        </div>
      </div>

      {/* Actions */}
      <div className="flex gap-3 pt-2">
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
