"use client";

import { useState, useEffect } from "react";
import { Mail } from "lucide-react";
import { notify } from "@/lib/notifications";
import { useAuthToken } from "@/lib/auth/useAuthToken";

interface Tool {
  id: string;
  name: string;
  description: string;
  tool_type: string;
  config: {
    default_subject?: string;
    message_body?: string;
    from_name?: string;
    from_email?: string;
  };
  is_active: boolean;
}

interface SendEmailFormProps {
  onSuccess: (tool: any) => void;
  onCancel: () => void;
  tool?: Tool;
  accountId: string;
  toolSetId?: string;
}

interface FormData {
  name: string;
  description: string;
  default_subject: string;
  message_body: string;
  from_name: string;
  from_email: string;
}

interface FormErrors {
  name?: string;
  description?: string;
  message_body?: string;
  from_email?: string;
}

const DEFAULT_DESCRIPTION =
  "Send an email to the caller when they ask for a confirmation, link, or information by email.";

const TEMPLATE_VARIABLES = [
  { label: "{account_name}", hint: "Your business name" },
];

export default function SendEmailForm({ onSuccess, onCancel, tool, accountId, toolSetId }: SendEmailFormProps) {
  const isEditMode = !!tool;
  const { authFetch } = useAuthToken();

  const [formData, setFormData] = useState<FormData>({
    name: "",
    description: DEFAULT_DESCRIPTION,
    default_subject: "",
    message_body: "",
    from_name: "",
    from_email: "",
  });

  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<FormErrors>({});

  useEffect(() => {
    if (tool) {
      setFormData({
        name: tool.name || "",
        description: tool.description || DEFAULT_DESCRIPTION,
        default_subject: tool.config?.default_subject || "",
        message_body: tool.config?.message_body || "",
        from_name: tool.config?.from_name || "",
        from_email: tool.config?.from_email || "",
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
      newErrors.message_body = "Default message body is required";
    }
    if (formData.from_email.trim() && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(formData.from_email.trim())) {
      newErrors.from_email = "Must be a valid email address";
    }
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validateForm()) return;

    setSaving(true);
    try {
      const config: Record<string, string> = {
        message_body: formData.message_body.trim(),
      };
      if (formData.default_subject.trim()) config.default_subject = formData.default_subject.trim();
      if (formData.from_name.trim()) config.from_name = formData.from_name.trim();
      if (formData.from_email.trim()) config.from_email = formData.from_email.trim();

      const payload = {
        name: formData.name.trim(),
        description: formData.description.trim(),
        tool_type: "SEND_EMAIL",
        config,
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
    const textarea = document.getElementById("email-message-body") as HTMLTextAreaElement | null;
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
        <div className="w-12 h-12 rounded-lg bg-blue-600/20 flex items-center justify-center">
          <Mail className="text-blue-400" size={24} />
        </div>
        <div>
          <h3 className="font-semibold">{isEditMode ? "Edit" : "Create"} Send Email Tool</h3>
          <p className="text-sm text-gray-400">
            Email a guest mid-call — confirmations, links, booking details, and more
          </p>
        </div>
      </div>

      {/* Tool Name */}
      <div>
        <label className="block text-sm font-medium mb-2">
          Tool Name <span className="text-red-500">*</span>
        </label>
        <input
          type="text"
          value={formData.name}
          onChange={(e) => handleChange("name", e.target.value)}
          placeholder="e.g., send_booking_confirmation"
          className={`w-full px-4 py-3 bg-[#141414] border ${
            errors.name ? "border-red-500" : "border-gray-800"
          } rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 focus:border-transparent`}
        />
        <p className="text-xs text-gray-500 mt-1">
          Used internally by the AI (lowercase, underscores)
        </p>
        {errors.name && <p className="text-xs text-red-500 mt-1">{errors.name}</p>}
      </div>

      {/* Trigger description */}
      <div>
        <label className="block text-sm font-medium mb-2">
          When should the AI use this? <span className="text-red-500">*</span>
        </label>
        <textarea
          value={formData.description}
          onChange={(e) => handleChange("description", e.target.value)}
          placeholder="e.g., Send an email when the caller asks for a confirmation or summary by email"
          rows={3}
          className={`w-full px-4 py-3 bg-[#141414] border ${
            errors.description ? "border-red-500" : "border-gray-800"
          } rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 focus:border-transparent resize-none`}
        />
        <p className="text-xs text-gray-500 mt-1">
          The AI reads this to decide when to send the email — be specific
        </p>
        {errors.description && (
          <p className="text-xs text-red-500 mt-1">{errors.description}</p>
        )}
      </div>

      {/* Default subject */}
      <div>
        <label className="block text-sm font-medium mb-2">
          Default Subject Line
        </label>
        <input
          type="text"
          value={formData.default_subject}
          onChange={(e) => handleChange("default_subject", e.target.value)}
          placeholder="e.g., Your booking confirmation"
          className="w-full px-4 py-3 bg-[#141414] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 focus:border-transparent"
        />
        <p className="text-xs text-gray-500 mt-1">
          Used when the AI doesn&apos;t provide its own subject. If blank, a generic subject is used.
        </p>
      </div>

      {/* Message body */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <label className="block text-sm font-medium">
            Default Message Body <span className="text-red-500">*</span>
          </label>
          <div className="flex items-center gap-1 flex-wrap justify-end">
            {TEMPLATE_VARIABLES.map((v) => (
              <button
                key={v.label}
                type="button"
                title={v.hint}
                onClick={() => insertVariable(v.label)}
                className="text-xs px-2 py-1 bg-gray-800 hover:bg-gray-700 text-blue-400 rounded font-mono transition-colors"
              >
                {v.label}
              </button>
            ))}
          </div>
        </div>
        <textarea
          id="email-message-body"
          value={formData.message_body}
          onChange={(e) => handleChange("message_body", e.target.value)}
          placeholder={"e.g., Hi, thanks for calling {account_name}! Here are your booking details…"}
          rows={5}
          className={`w-full px-4 py-3 bg-[#141414] border ${
            errors.message_body ? "border-red-500" : "border-gray-800"
          } rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 focus:border-transparent resize-none font-mono text-sm`}
        />
        <p className="text-xs text-gray-500 mt-1">
          Sent when the AI doesn&apos;t compose its own message. Use the button above to insert variables.
        </p>
        {errors.message_body && (
          <p className="text-xs text-red-500 mt-1">{errors.message_body}</p>
        )}
      </div>

      {/* Optional sender override */}
      <div className="border border-gray-800 rounded-lg p-4 space-y-4">
        <div>
          <p className="text-sm font-medium">Sender Override <span className="text-gray-500 font-normal">(optional)</span></p>
          <p className="text-xs text-gray-500 mt-0.5">
            Overrides the account-level sender for this tool only. Leave blank to use your account&apos;s default sender.
          </p>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-medium mb-1 text-gray-400">From Name</label>
            <input
              type="text"
              value={formData.from_name}
              onChange={(e) => handleChange("from_name", e.target.value)}
              placeholder="e.g., Grand Hotel"
              className="w-full px-3 py-2 bg-[#141414] border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600 focus:border-transparent"
            />
          </div>
          <div>
            <label className="block text-xs font-medium mb-1 text-gray-400">From Email</label>
            <input
              type="email"
              value={formData.from_email}
              onChange={(e) => handleChange("from_email", e.target.value)}
              placeholder="e.g., concierge@hotel.com"
              className={`w-full px-3 py-2 bg-[#141414] border ${
                errors.from_email ? "border-red-500" : "border-gray-800"
              } rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600 focus:border-transparent`}
            />
            {errors.from_email && (
              <p className="text-xs text-red-500 mt-1">{errors.from_email}</p>
            )}
          </div>
        </div>
      </div>

      <div className="flex gap-3 pt-2">
        <button
          type="submit"
          disabled={saving}
          className="flex-1 px-4 py-3 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg transition-colors font-medium"
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
