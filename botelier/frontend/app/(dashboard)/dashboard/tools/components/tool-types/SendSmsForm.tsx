"use client";

import { useState, useEffect } from "react";
import { MessageSquare } from "lucide-react";
import { notify } from "@/lib/notifications";
import { useAuthToken } from "@/lib/auth/useAuthToken";

interface Tool {
  id: string;
  name: string;
  description: string;
  tool_type: string;
  config: {
    message_body?: string;
  };
  is_active: boolean;
}

interface SendSmsFormProps {
  onSuccess: (tool: any) => void;
  onCancel: () => void;
  tool?: Tool;
  accountId: string;
  toolSetId?: string;
}

interface FormData {
  name: string;
  description: string;
  message_body: string;
}

interface FormErrors {
  name?: string;
  description?: string;
  message_body?: string;
}

const DEFAULT_DESCRIPTION =
  "Send an SMS to the caller when they request a confirmation, link, or summary by text message.";

const TEMPLATE_VARIABLES = [
  { label: "{caller_name}", hint: "Caller's name" },
  { label: "{caller_number}", hint: "Caller's phone number" },
  { label: "{account_name}", hint: "Your business name" },
];

export default function SendSmsForm({ onSuccess, onCancel, tool, accountId, toolSetId }: SendSmsFormProps) {
  const isEditMode = !!tool;
  const { authFetch } = useAuthToken();

  const [formData, setFormData] = useState<FormData>({
    name: "",
    description: DEFAULT_DESCRIPTION,
    message_body: "",
  });

  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<FormErrors>({});

  useEffect(() => {
    if (tool) {
      setFormData({
        name: tool.name || "",
        description: tool.description || DEFAULT_DESCRIPTION,
        message_body: tool.config?.message_body || "",
      });
    }
  }, [tool]);

  const validateForm = (): boolean => {
    const newErrors: FormErrors = {};
    if (!formData.name.trim()) {
      newErrors.name = "Tool name is required";
    }
    if (!formData.description.trim()) {
      newErrors.description = "Trigger description is required";
    }
    if (!formData.message_body.trim()) {
      newErrors.message_body = "Message body is required";
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
        tool_type: "SEND_SMS",
        config: {
          message_body: formData.message_body.trim(),
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
      notify.error(
        error instanceof Error
          ? error.message
          : `Failed to ${isEditMode ? "update" : "create"} tool. Please try again.`
      );
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

  const insertVariable = (variable: string) => {
    const textarea = document.getElementById("sms-message-body") as HTMLTextAreaElement | null;
    if (!textarea) {
      handleChange("message_body", formData.message_body + variable);
      return;
    }
    const start = textarea.selectionStart ?? formData.message_body.length;
    const end = textarea.selectionEnd ?? formData.message_body.length;
    const updated =
      formData.message_body.substring(0, start) + variable + formData.message_body.substring(end);
    handleChange("message_body", updated);
    setTimeout(() => {
      textarea.setSelectionRange(start + variable.length, start + variable.length);
      textarea.focus();
    }, 0);
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <div className="flex items-center gap-3 pb-4 border-b border-gray-800">
        <div className="w-12 h-12 rounded-lg bg-green-600/20 flex items-center justify-center">
          <MessageSquare className="text-green-500" size={24} />
        </div>
        <div>
          <h3 className="font-semibold">{isEditMode ? "Edit" : "Create"} Send SMS Tool</h3>
          <p className="text-sm text-gray-400">
            Text the caller a message mid-call — confirmations, links, summaries, and more
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
          placeholder="e.g., send_confirmation_sms"
          className={`w-full px-4 py-3 bg-[#141414] border ${
            errors.name ? "border-red-500" : "border-gray-800"
          } rounded-lg focus:outline-none focus:ring-2 focus:ring-green-600 focus:border-transparent`}
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
          placeholder="e.g., Send an SMS when the caller asks for a confirmation or link by text"
          rows={3}
          className={`w-full px-4 py-3 bg-[#141414] border ${
            errors.description ? "border-red-500" : "border-gray-800"
          } rounded-lg focus:outline-none focus:ring-2 focus:ring-green-600 focus:border-transparent resize-none`}
        />
        <p className="text-xs text-gray-500 mt-1">
          The AI reads this to decide when to send the SMS — be specific about the trigger
        </p>
        {errors.description && (
          <p className="text-xs text-red-500 mt-1">{errors.description}</p>
        )}
      </div>

      <div>
        <div className="flex items-center justify-between mb-2">
          <label className="block text-sm font-medium">
            Message Body <span className="text-red-500">*</span>
          </label>
          <div className="flex items-center gap-1 flex-wrap justify-end">
            {TEMPLATE_VARIABLES.map((v) => (
              <button
                key={v.label}
                type="button"
                title={v.hint}
                onClick={() => insertVariable(v.label)}
                className="text-xs px-2 py-1 bg-gray-800 hover:bg-gray-700 text-green-400 rounded font-mono transition-colors"
              >
                {v.label}
              </button>
            ))}
          </div>
        </div>
        <textarea
          id="sms-message-body"
          value={formData.message_body}
          onChange={(e) => handleChange("message_body", e.target.value)}
          placeholder="e.g., Hi {caller_name}, here's the link you requested: https://example.com/booking"
          rows={4}
          className={`w-full px-4 py-3 bg-[#141414] border ${
            errors.message_body ? "border-red-500" : "border-gray-800"
          } rounded-lg focus:outline-none focus:ring-2 focus:ring-green-600 focus:border-transparent resize-none font-mono text-sm`}
        />
        <p className="text-xs text-gray-500 mt-1">
          Use the buttons above to insert dynamic variables. Sent as-is to the caller&apos;s phone number.
        </p>
        {errors.message_body && (
          <p className="text-xs text-red-500 mt-1">{errors.message_body}</p>
        )}
      </div>

      <div className="flex gap-3 pt-2">
        <button
          type="submit"
          disabled={saving}
          className="flex-1 px-4 py-3 bg-green-600 hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg transition-colors font-medium"
        >
          {saving
            ? isEditMode ? "Saving..." : "Creating..."
            : isEditMode ? "Save Changes" : "Create Tool"}
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
