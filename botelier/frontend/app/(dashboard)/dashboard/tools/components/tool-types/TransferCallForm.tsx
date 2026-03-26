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
    extension_pause_seconds?: number;
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
  extension_pause_seconds: number;
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

const COUNTRY_CODE_OPTIONS: { label: string; value: string }[] = [
  { label: "United States +1", value: "+1" },
  { label: "Canada +1", value: "+1" },
  { label: "United Kingdom +44", value: "+44" },
  { label: "Australia +61", value: "+61" },
  { label: "Mexico +52", value: "+52" },
  { label: "Afghanistan +93", value: "+93" },
  { label: "Albania +355", value: "+355" },
  { label: "Algeria +213", value: "+213" },
  { label: "Andorra +376", value: "+376" },
  { label: "Argentina +54", value: "+54" },
  { label: "Armenia +374", value: "+374" },
  { label: "Austria +43", value: "+43" },
  { label: "Bahrain +973", value: "+973" },
  { label: "Bangladesh +880", value: "+880" },
  { label: "Belarus +375", value: "+375" },
  { label: "Belgium +32", value: "+32" },
  { label: "Bhutan +975", value: "+975" },
  { label: "Bolivia +591", value: "+591" },
  { label: "Bosnia & Herzegovina +387", value: "+387" },
  { label: "Brazil +55", value: "+55" },
  { label: "Bulgaria +359", value: "+359" },
  { label: "Cambodia +855", value: "+855" },
  { label: "Chile +56", value: "+56" },
  { label: "China +86", value: "+86" },
  { label: "Colombia +57", value: "+57" },
  { label: "Costa Rica +506", value: "+506" },
  { label: "Croatia +385", value: "+385" },
  { label: "Cuba +53", value: "+53" },
  { label: "Czech Republic +420", value: "+420" },
  { label: "Denmark +45", value: "+45" },
  { label: "Ecuador +593", value: "+593" },
  { label: "Egypt +20", value: "+20" },
  { label: "El Salvador +503", value: "+503" },
  { label: "Estonia +372", value: "+372" },
  { label: "Finland +358", value: "+358" },
  { label: "France +33", value: "+33" },
  { label: "Gambia +220", value: "+220" },
  { label: "Germany +49", value: "+49" },
  { label: "Greece +30", value: "+30" },
  { label: "Guatemala +502", value: "+502" },
  { label: "Haiti +509", value: "+509" },
  { label: "Honduras +504", value: "+504" },
  { label: "Hong Kong +852", value: "+852" },
  { label: "Hungary +36", value: "+36" },
  { label: "Iceland +354", value: "+354" },
  { label: "India +91", value: "+91" },
  { label: "Indonesia +62", value: "+62" },
  { label: "Iraq +964", value: "+964" },
  { label: "Ireland +353", value: "+353" },
  { label: "Israel +972", value: "+972" },
  { label: "Italy +39", value: "+39" },
  { label: "Japan +81", value: "+81" },
  { label: "Jordan +962", value: "+962" },
  { label: "Kazakhstan +7", value: "+7" },
  { label: "Kenya +254", value: "+254" },
  { label: "Kuwait +965", value: "+965" },
  { label: "Laos +856", value: "+856" },
  { label: "Latvia +371", value: "+371" },
  { label: "Liechtenstein +423", value: "+423" },
  { label: "Lithuania +370", value: "+370" },
  { label: "Libya +218", value: "+218" },
  { label: "Luxembourg +352", value: "+352" },
  { label: "Macau +853", value: "+853" },
  { label: "Malaysia +60", value: "+60" },
  { label: "Maldives +960", value: "+960" },
  { label: "Malta +356", value: "+356" },
  { label: "Moldova +373", value: "+373" },
  { label: "Monaco +377", value: "+377" },
  { label: "Mongolia +976", value: "+976" },
  { label: "Montenegro +382", value: "+382" },
  { label: "Morocco +212", value: "+212" },
  { label: "Myanmar +95", value: "+95" },
  { label: "Netherlands +31", value: "+31" },
  { label: "New Zealand +64", value: "+64" },
  { label: "Nicaragua +505", value: "+505" },
  { label: "Nigeria +234", value: "+234" },
  { label: "North Macedonia +389", value: "+389" },
  { label: "Norway +47", value: "+47" },
  { label: "Pakistan +92", value: "+92" },
  { label: "Panama +507", value: "+507" },
  { label: "Paraguay +595", value: "+595" },
  { label: "Peru +51", value: "+51" },
  { label: "Philippines +63", value: "+63" },
  { label: "Poland +48", value: "+48" },
  { label: "Portugal +351", value: "+351" },
  { label: "Qatar +974", value: "+974" },
  { label: "Romania +40", value: "+40" },
  { label: "Russia +7", value: "+7" },
  { label: "Saudi Arabia +966", value: "+966" },
  { label: "Senegal +221", value: "+221" },
  { label: "Serbia +381", value: "+381" },
  { label: "Singapore +65", value: "+65" },
  { label: "Slovakia +421", value: "+421" },
  { label: "Slovenia +386", value: "+386" },
  { label: "South Africa +27", value: "+27" },
  { label: "South Korea +82", value: "+82" },
  { label: "Spain +34", value: "+34" },
  { label: "Sri Lanka +94", value: "+94" },
  { label: "Sweden +46", value: "+46" },
  { label: "Switzerland +41", value: "+41" },
  { label: "Syria +963", value: "+963" },
  { label: "Taiwan +886", value: "+886" },
  { label: "Tanzania +255", value: "+255" },
  { label: "Thailand +66", value: "+66" },
  { label: "Tunisia +216", value: "+216" },
  { label: "Turkey +90", value: "+90" },
  { label: "Uganda +256", value: "+256" },
  { label: "Ukraine +380", value: "+380" },
  { label: "United Arab Emirates +971", value: "+971" },
  { label: "Uruguay +598", value: "+598" },
  { label: "Venezuela +58", value: "+58" },
  { label: "Vietnam +84", value: "+84" },
  { label: "Zambia +260", value: "+260" },
  { label: "Zimbabwe +263", value: "+263" },
];

const KNOWN_COUNTRY_CODES = COUNTRY_CODE_OPTIONS
  .map((o) => o.value)
  .filter((v, i, a) => a.indexOf(v) === i);

const EXTENSION_PAUSE_OPTIONS = [
  { label: "0.5 s", value: 0.5 },
  { label: "1 s (default)", value: 1 },
  { label: "1.5 s", value: 1.5 },
  { label: "2 s", value: 2 },
  { label: "2.5 s", value: 2.5 },
  { label: "3 s", value: 3 },
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
    extension_pause_seconds: 1,
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
        extension_pause_seconds: tool.config?.extension_pause_seconds ?? 1,
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
          extension_pause_seconds: formData.extension.trim() ? formData.extension_pause_seconds : null,
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
  const hasExtension = formData.extension.trim().length > 0;

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

        <select
          value={formData.country_code}
          onChange={(e) => handleChange("country_code", e.target.value)}
          className="w-full px-4 py-3 bg-[#141414] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 focus:border-transparent mb-2"
        >
          {COUNTRY_CODE_OPTIONS.map((cc) => (
            <option key={cc.label} value={cc.value}>
              {cc.label}
            </option>
          ))}
        </select>

        <input
          type="text"
          inputMode="numeric"
          value={formData.phone_number}
          onChange={(e) => handleChange("phone_number", e.target.value.replace(/[^\d]/g, "").slice(0, 15))}
          placeholder={phonePlaceholder}
          className={`w-full px-4 py-3 bg-[#141414] border ${
            errors.phone_number ? "border-red-500" : "border-gray-800"
          } rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 focus:border-transparent`}
        />

        {errors.phone_number && (
          <p className="text-xs text-red-500 mt-1">{errors.phone_number}</p>
        )}
        {!errors.phone_number && (
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
        {errors.extension && (
          <p className="text-xs text-red-500 mt-1">{errors.extension}</p>
        )}
        {!errors.extension && (
          <p className="text-xs text-gray-500 mt-1">
            The system will automatically dial this after connecting.
          </p>
        )}

        {hasExtension && (
          <div className="mt-3">
            <label className="block text-sm font-medium mb-2">
              Pause before extension
            </label>
            <select
              value={formData.extension_pause_seconds}
              onChange={(e) => handleChange("extension_pause_seconds", parseFloat(e.target.value))}
              className="w-full px-4 py-3 bg-[#141414] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 focus:border-transparent"
            >
              {EXTENSION_PAUSE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
            <p className="text-xs text-gray-500 mt-1">
              How long to wait after connecting before dialing the extension. Increase if the PBX prompt is slow.
            </p>
          </div>
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
