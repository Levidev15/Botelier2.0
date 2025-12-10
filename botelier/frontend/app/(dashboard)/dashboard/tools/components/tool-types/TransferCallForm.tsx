"use client";

import { useState, useEffect } from "react";
import { Phone } from "lucide-react";
import { notify } from "@/lib/notifications";

interface Tool {
  id: string;
  name: string;
  description: string;
  tool_type: string;
  config: {
    phone_number?: string;
    pre_transfer_message?: string;
  };
  is_active: boolean;
}

interface TransferCallFormProps {
  onSuccess: (tool: any) => void;
  onCancel: () => void;
  tool?: Tool;
  accountId: string;
}

interface FormData {
  name: string;
  description: string;
  phone_number: string;
  pre_transfer_message: string;
}

export default function TransferCallForm({ onSuccess, onCancel, tool, accountId }: TransferCallFormProps) {
  const isEditMode = !!tool;
  
  const [formData, setFormData] = useState<FormData>({
    name: "",
    description: "",
    phone_number: "",
    pre_transfer_message: "Let me connect you with someone who can help...",
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
        },
        hotel_id: accountId,
        is_active: true,
      };

      const url = isEditMode ? `/api/tools/${tool.id}?hotel_id=${accountId}` : "/api/tools";
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
        throw new Error(errorData.detail || `Failed to ${isEditMode ? 'update' : 'create'} tool`);
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
