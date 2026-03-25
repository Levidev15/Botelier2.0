"use client";

import { useState, useEffect } from "react";
import { Phone, PhoneForwarded, AlertTriangle } from "lucide-react";
import { notify } from "@/lib/notifications";
import { useAuthToken } from "@/lib/auth/useAuthToken";

interface Tool {
  id: string;
  name: string;
  description: string;
  tool_type: string;
  config: {
    phone_number?: string;
    country_code?: string;
    extension?: string;
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
  country_code: string;
  phone_number: string;
  extension: string;
  pre_transfer_message: string;
  transfer_mode: "warm" | "cold";
}

interface FormErrors {
  name?: string;
  description?: string;
  country_code?: string;
  phone_number?: string;
  extension?: string;
}

const COMMON_COUNTRY_CODES = [
  { label: "US +1", value: "+1" },
  { label: "CA +1", value: "+1" },
  { label: "GB +44", value: "+44" },
  { label: "AU +61", value: "+61" },
  { label: "MX +52", value: "+52" },
];

const KNOWN_COUNTRY_CODES = [
  "+1",
  "+7",
  "+20", "+27", "+30", "+31", "+32", "+33", "+34", "+36",
  "+39", "+40", "+41", "+43", "+44", "+45", "+46", "+47", "+48", "+49",
  "+51", "+52", "+53", "+54", "+55", "+56", "+57", "+58",
  "+60", "+61", "+62", "+63", "+64", "+65", "+66",
  "+81", "+82", "+84", "+86",
  "+90", "+91", "+92", "+93", "+94", "+95",
  "+212", "+213", "+216", "+218", "+220", "+221",
  "+234", "+254", "+255", "+256", "+260", "+263",
  "+351", "+352", "+353", "+354", "+355", "+356",
  "+358", "+359", "+370", "+371", "+372", "+373",
  "+374", "+375", "+376", "+377", "+380", "+381",
  "+382", "+385", "+386", "+387", "+389",
  "+420", "+421", "+423",
  "+502", "+503", "+504", "+505", "+506", "+507",
  "+509", "+591", "+593", "+595", "+598",
  "+852", "+853", "+855", "+856",
  "+880", "+886",
  "+960", "+962", "+963", "+964", "+965", "+966",
  "+971", "+972", "+973", "+974", "+975", "+976",
];

function parseE164(e164: string): { countryCode: string; localNumber: string } {
  if (!e164.startsWith("+")) {
    return { countryCode: "+1", localNumber: e164 };
  }
  for (const cc of KNOWN_COUNTRY_CODES) {
    if (e164.startsWith(cc)) {
      const local = e164.slice(cc.length);
      if (local.length >= 4) {
        return { countryCode: cc, localNumber: local };
      }
    }
  }
  return { countryCode: "+1", localNumber: e164.slice(1) };
}

export default function TransferCallForm({ onSuccess, onCancel, tool, accountId, toolSetId }: TransferCallFormProps) {
  const isEditMode = !!tool;
  const { authFetch } = useAuthToken();

  const [formData, setFormData] = useState<FormData>({
    name: "",
    description: "",
    country_code: "+1",
    phone_number: "",
    extension: "",
    pre_transfer_message: "Let me connect you with someone who can help...",
    transfer_mode: "warm",
  });

  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<FormErrors>({});

  useEffect(() => {
    if (tool) {
      const rawPhone = tool.config?.phone_number || "";
      let countryCode: string;
      let localNumber: string;

      if (rawPhone.startsWith("+")) {
        const parsed = parseE164(rawPhone);
        countryCode = parsed.countryCode;
        localNumber = parsed.localNumber;
      } else {
        countryCode = tool.config?.country_code || "+1";
        localNumber = rawPhone;
      }

      setFormData({
        name: tool.name || "",
        description: tool.description || "",
        country_code: countryCode,
        phone_number: localNumber,
        extension: tool.config?.extension || "",
        pre_transfer_message: tool.config?.pre_transfer_message || "Let me connect you with someone who can help...",
        transfer_mode: (tool.config?.transfer_mode as "warm" | "cold") || "warm",
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

    if (!formData.country_code.trim()) {
      newErrors.country_code = "Country code is required";
    } else if (!/^\+\d{1,4}$/.test(formData.country_code)) {
      newErrors.country_code = "Must be + followed by 1–4 digits (e.g. +1, +44)";
    }

    if (!formData.phone_number.trim()) {
      newErrors.phone_number = "Phone number is required";
    } else if (!/^\d+$/.test(formData.phone_number)) {
      newErrors.phone_number = "Digits only — no spaces, dashes, or country code";
    } else if (formData.country_code === "+1" && formData.phone_number.length !== 10) {
      newErrors.phone_number = "US/CA numbers must be exactly 10 digits";
    } else if (formData.country_code !== "+1" && (formData.phone_number.length < 5 || formData.phone_number.length > 15)) {
      newErrors.phone_number = "Phone number must be 5–15 digits";
    }

    if (formData.extension.trim() && !/^\d{1,20}$/.test(formData.extension.trim())) {
      newErrors.extension = "Extension must be digits only (max 20)";
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
          country_code: formData.country_code,
          phone_number: formData.phone_number,
          extension: formData.extension.trim() || null,
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

  const isUs = formData.country_code === "+1";
  const phonePlaceholder = isUs ? "5550123456" : "Enter local number";

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <div className="flex items-center gap-3 pb-4 border-b border-gray-800">
        <div className="w-12 h-12 rounded-lg bg-blue-600/20 flex items-center justify-center">
          <Phone className="text-blue-500" size={24} />
        </div>
        <div>
          <h3 className="font-semibold">{isEditMode ? "Edit" : "Create"} Transfer Call Tool</h3>
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

        <div className="flex gap-2">
          <div className="relative flex-shrink-0">
            <div className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 text-sm font-medium pointer-events-none">
              +
            </div>
            <input
              type="text"
              value={formData.country_code.replace(/^\+/, "")}
              onChange={(e) => {
                const raw = e.target.value.replace(/[^\d]/g, "").slice(0, 4);
                handleChange("country_code", raw ? `+${raw}` : "+");
              }}
              placeholder="1"
              className={`w-16 pl-6 pr-2 py-3 bg-[#141414] border ${
                errors.country_code ? "border-red-500" : "border-gray-800"
              } rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 focus:border-transparent text-center`}
            />
          </div>

          <input
            type="text"
            inputMode="numeric"
            value={formData.phone_number}
            onChange={(e) => handleChange("phone_number", e.target.value.replace(/[^\d]/g, "").slice(0, 15))}
            placeholder={phonePlaceholder}
            className={`flex-1 px-4 py-3 bg-[#141414] border ${
              errors.phone_number ? "border-red-500" : "border-gray-800"
            } rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 focus:border-transparent`}
          />
        </div>

        <div className="flex flex-wrap gap-1.5 mt-2">
          {COMMON_COUNTRY_CODES.map((cc) => (
            <button
              key={cc.label}
              type="button"
              onClick={() => handleChange("country_code", cc.value)}
              className={`px-2 py-1 text-xs rounded border transition-colors ${
                formData.country_code === cc.value
                  ? "border-blue-600 bg-blue-600/10 text-blue-400"
                  : "border-gray-700 bg-[#141414] text-gray-400 hover:border-gray-600 hover:text-gray-300"
              }`}
            >
              {cc.label}
            </button>
          ))}
        </div>

        {errors.country_code && (
          <p className="text-xs text-red-500 mt-1">{errors.country_code}</p>
        )}
        {errors.phone_number && (
          <p className="text-xs text-red-500 mt-1">{errors.phone_number}</p>
        )}
        {!errors.phone_number && !errors.country_code && (
          <p className="text-xs text-gray-500 mt-1">
            {isUs ? "10-digit US/CA number (e.g. 5550123456)" : "Local digits only — no country code prefix"}
          </p>
        )}
      </div>

      <div>
        <label className="block text-sm font-medium mb-2">
          Extension <span className="text-gray-500 font-normal">(optional)</span>
        </label>
        <input
          type="text"
          inputMode="numeric"
          value={formData.extension}
          onChange={(e) => handleChange("extension", e.target.value.replace(/[^\d]/g, "").slice(0, 20))}
          placeholder="e.g. 1042"
          className={`w-full px-4 py-3 bg-[#141414] border ${
            errors.extension ? "border-red-500" : "border-gray-800"
          } rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 focus:border-transparent`}
        />
        <p className="text-xs text-gray-500 mt-1">
          The system will automatically dial this after connecting.
        </p>
        {errors.extension && (
          <p className="text-xs text-red-500 mt-1">{errors.extension}</p>
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
