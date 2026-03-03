"use client";

import { useState, useEffect } from "react";
import { Phone, PhoneForwarded, AlertTriangle } from "lucide-react";
import { notify } from "@/lib/notifications";

interface Tool {
  id: string;
  name: string;
  description: string;
  tool_type: string;
  config: {
    phone_number?: string;
    pre_transfer_message?: string;
    transfer_mode?: string;
  };
  is_active: boolean;
}

interface TransferCallFormProps {
  onSuccess: (tool: any) => void;
  onCancel: () => void;
  tool?: Tool;
  accountId: string;
  toolSetId?: string;
}

interface FormData {
  name: string;
  description: string;
  phone_number: string;
  pre_transfer_message: string;
  transfer_mode: "warm" | "cold";
}

export default function TransferCallForm({ onSuccess, onCancel, tool, accountId, toolSetId }: TransferCallFormProps) {
  const isEditMode = !!tool;
  
  const [formData, setFormData] = useState<FormData>({
    name: "",
    description: "",
    phone_number: "",
    pre_transfer_message: "Let me connect you with someone who can help...",
    transfer_mode: "warm",
  });

  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<Partial<FormData>>({});

  useEffect(() => {
    if (tool) {
      setFormData({
        name: tool.name || "",
        description: tool.description || "",
        phone_number: tool.config?.phone_number || "",
        pre_transfer_message: tool.config?.pre_transfer_message || "Let me connect you with someone who can help...",
        transfer_mode: (tool.config?.transfer_mode as "warm" | "cold") || "warm",
      });
    }
  }, [tool]);

  const validateForm = (): boolean => {
    const newErrors: Partial<FormData> = {};

    if (!formData.name.trim()) {
      newErrors.name = "Tool name is required";
    }

    if (!formData.description.trim()) {
      newErrors.description = "Description is required";
    }

    if (!formData.phone_number.trim()) {
      newErrors.phone_number = "Phone number is required";
    } else if (!/^[\+\d][\d\s\-\(\)]+$/.test(formData.phone_number)) {
      newErrors.phone_number = "Invalid phone number format";
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
        tool_type: "TRANSFER_CALL",
        config: {
          phone_number: formData.phone_number,
          pre_transfer_message: formData.pre_transfer_message,
          transfer_mode: formData.transfer_mode,
        },
        tool_set_id: toolSetId,
        is_active: true,
      };

      const scopeParam = toolSetId ? `tool_set_id=${toolSetId}` : `hotel_id=${accountId}`;
      const url = isEditMode
        ? `/api/tools/${tool.id}?${scopeParam}`
        : "/api/tools";
      const method = isEditMode ? "PUT" : "POST";

      const response = await fetch(url, {
        method,
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        const errorData = await response.json();
        let errorMsg = `Failed to ${isEditMode ? 'update' : 'create'} tool`;
        if (typeof errorData.detail === "string") {
          errorMsg = errorData.detail;
        } else if (Array.isArray(errorData.detail)) {
          errorMsg = errorData.detail.map((e: any) => e.msg || e.message || JSON.stringify(e)).join(", ");
        }
        throw new Error(errorMsg);
      }

      const savedTool = await response.json();
      notify.success(`Tool ${isEditMode ? 'updated' : 'created'} successfully`);
      onSuccess(savedTool);
    } catch (error) {
      console.error(`Error ${isEditMode ? 'updating' : 'creating'} tool:`, error);
      notify.error(error instanceof Error ? error.message : `Failed to ${isEditMode ? 'update' : 'create'} tool. Please try again.`);
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
        <div className="w-12 h-12 rounded-lg bg-blue-600/20 flex items-center justify-center">
          <Phone className="text-blue-500" size={24} />
        </div>
        <div>
          <h3 className="font-semibold">{isEditMode ? 'Edit' : 'Create'} Transfer Call Tool</h3>
          <p className="text-sm text-gray-400">
            Route calls to human agents or other phone numbers
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
          placeholder="e.g., transfer_to_front_desk"
          className={`w-full px-4 py-3 bg-[#141414] border ${
            errors.name ? "border-red-500" : "border-gray-800"
          } rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 focus:border-transparent`}
        />
        <p className="text-xs text-gray-500 mt-1">
          This name will be used internally by the AI (use lowercase, underscores)
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
          placeholder="Describe what this tool does and when the AI should use it"
          rows={3}
          className={`w-full px-4 py-3 bg-[#141414] border ${
            errors.description ? "border-red-500" : "border-gray-800"
          } rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 focus:border-transparent resize-none`}
        />
        <p className="text-xs text-gray-500 mt-1">
          The AI uses this to decide when to call this function
        </p>
        {errors.description && (
          <p className="text-xs text-red-500 mt-1">{errors.description}</p>
        )}
      </div>

      <div>
        <label className="block text-sm font-medium mb-2">
          Transfer to Phone Number <span className="text-red-500">*</span>
        </label>
        <input
          type="tel"
          value={formData.phone_number}
          onChange={(e) => handleChange("phone_number", e.target.value)}
          placeholder="+1-555-0123"
          className={`w-full px-4 py-3 bg-[#141414] border ${
            errors.phone_number ? "border-red-500" : "border-gray-800"
          } rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 focus:border-transparent`}
        />
        <p className="text-xs text-gray-500 mt-1">
          Use E.164 format (e.g., +1-555-0123 for US numbers)
        </p>
        {errors.phone_number && (
          <p className="text-xs text-red-500 mt-1">{errors.phone_number}</p>
        )}
      </div>

      <div>
        <label className="block text-sm font-medium mb-2">
          Pre-Transfer Message
        </label>
        <textarea
          value={formData.pre_transfer_message}
          onChange={(e) => handleChange("pre_transfer_message", e.target.value)}
          placeholder="What the AI says before transferring"
          rows={2}
          className="w-full px-4 py-3 bg-[#141414] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 focus:border-transparent resize-none"
        />
        <p className="text-xs text-gray-500 mt-1">
          The AI will say this message before transferring the call
        </p>
      </div>

      <div>
        <label className="block text-sm font-medium mb-3">
          Transfer Mode
        </label>
        <div className="grid grid-cols-1 gap-3">
          <button
            type="button"
            onClick={() => handleChange("transfer_mode", "warm")}
            className={`w-full text-left px-4 py-3 rounded-lg border transition-colors ${
              formData.transfer_mode === "warm"
                ? "border-blue-600 bg-blue-600/10"
                : "border-gray-800 bg-[#141414] hover:border-gray-700"
            }`}
          >
            <div className="flex items-start gap-3">
              <div className={`mt-0.5 w-4 h-4 rounded-full border-2 flex items-center justify-center flex-shrink-0 ${
                formData.transfer_mode === "warm" ? "border-blue-500" : "border-gray-600"
              }`}>
                {formData.transfer_mode === "warm" && (
                  <div className="w-2 h-2 rounded-full bg-blue-500" />
                )}
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <PhoneForwarded className="h-4 w-4 text-blue-400" />
                  <span className="font-medium text-sm">Warm Transfer</span>
                </div>
                <p className="text-xs text-gray-500 mt-1">
                  Twilio stays in the bridge for both legs. Full call logging and duration tracking. Standard per-minute charges apply for the entire duration.
                </p>
              </div>
            </div>
          </button>

          <button
            type="button"
            onClick={() => handleChange("transfer_mode", "cold")}
            className={`w-full text-left px-4 py-3 rounded-lg border transition-colors ${
              formData.transfer_mode === "cold"
                ? "border-amber-600 bg-amber-600/10"
                : "border-gray-800 bg-[#141414] hover:border-gray-700"
            }`}
          >
            <div className="flex items-start gap-3">
              <div className={`mt-0.5 w-4 h-4 rounded-full border-2 flex items-center justify-center flex-shrink-0 ${
                formData.transfer_mode === "cold" ? "border-amber-500" : "border-gray-600"
              }`}>
                {formData.transfer_mode === "cold" && (
                  <div className="w-2 h-2 rounded-full bg-amber-500" />
                )}
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <PhoneForwarded className="h-4 w-4 text-amber-400" />
                  <span className="font-medium text-sm">Cold Transfer (SIP REFER)</span>
                </div>
                <p className="text-xs text-gray-500 mt-1">
                  Twilio exits the bridge after handoff. Charges stop at the moment of transfer — no ongoing bridging cost. Call outcome is not tracked after handoff.
                </p>
              </div>
            </div>
          </button>
        </div>

        {formData.transfer_mode === "cold" && (
          <div className="mt-3 flex items-start gap-2 px-3 py-2.5 bg-amber-950/30 border border-amber-800/50 rounded-lg">
            <AlertTriangle className="h-4 w-4 text-amber-500 flex-shrink-0 mt-0.5" />
            <p className="text-xs text-amber-400">
              After transfer, Botelier can no longer monitor, record, or log the duration of this call. Only the AI conversation portion will appear in call logs.
            </p>
          </div>
        )}
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
          className="flex-1 px-6 py-3 bg-blue-600 hover:bg-blue-700 rounded-lg font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {saving ? (isEditMode ? "Saving..." : "Creating...") : (isEditMode ? "Save Changes" : "Create Tool")}
        </button>
      </div>
    </form>
  );
}
