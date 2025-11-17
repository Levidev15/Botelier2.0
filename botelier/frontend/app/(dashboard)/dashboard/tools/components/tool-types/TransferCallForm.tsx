"use client";

import { useState } from "react";
import { Phone } from "lucide-react";

interface TransferCallFormProps {
  onSuccess: (tool: any) => void;
  onCancel: () => void;
}

interface FormData {
  name: string;
  description: string;
  phone_number: string;
  pre_transfer_message: string;
}

export default function TransferCallForm({ onSuccess, onCancel }: TransferCallFormProps) {
  const [formData, setFormData] = useState<FormData>({
    name: "",
    description: "",
    phone_number: "",
    pre_transfer_message: "Let me connect you with someone who can help...",
  });

  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<Partial<FormData>>({});

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
        tool_type: "transfer_call",
        config: {
          phone_number: formData.phone_number,
          pre_transfer_message: formData.pre_transfer_message,
        },
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
        throw new Error("Failed to create tool");
      }

      const newTool = await response.json();
      onSuccess(newTool);
    } catch (error) {
      console.error("Error creating tool:", error);
      alert("Failed to create tool. Please try again.");
    } finally {
      setSaving(false);
    }
  };

  const handleChange = (field: keyof FormData, value: string) => {
    setFormData({ ...formData, [field]: value });
    // Clear error when user starts typing
    if (errors[field]) {
      setErrors({ ...errors, [field]: undefined });
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3 pb-4 border-b border-gray-800">
        <div className="w-12 h-12 rounded-lg bg-blue-600/20 flex items-center justify-center">
          <Phone className="text-blue-500" size={24} />
        </div>
        <div>
          <h3 className="font-semibold">Transfer Call Configuration</h3>
          <p className="text-sm text-gray-400">
            Route calls to human agents or other phone numbers
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

      {/* Description */}
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

      {/* Phone Number */}
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

      {/* Pre-transfer Message */}
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

      {/* Actions */}
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
          {saving ? "Creating..." : "Create Tool"}
        </button>
      </div>
    </form>
  );
}
