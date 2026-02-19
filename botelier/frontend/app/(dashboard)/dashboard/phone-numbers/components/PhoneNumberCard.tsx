"use client";

import { useState } from "react";
import { Phone, Trash2, MessageSquare } from "lucide-react";
import { notify } from "@/lib/notifications";

interface Assistant {
  id: string;
  name: string;
}

interface PhoneNumberCardProps {
  phoneNumber: {
    id: string;
    phone_number: string;
    friendly_name: string | null;
    country_code: string;
    assistant_id: string | null;
    hotel_id: string;
    is_active: boolean;
    sms_enabled?: boolean;
    sms_assistant_id?: string | null;
  };
  assistants: Assistant[];
  onDelete: (id: string) => void;
  onUpdate: () => void;
}

export default function PhoneNumberCard({ phoneNumber, assistants, onDelete, onUpdate }: PhoneNumberCardProps) {
  const [assigning, setAssigning] = useState(false);
  const [toggingSms, setTogglingSms] = useState(false);

  const handleAssignment = async (assistantId: string) => {
    setAssigning(true);
    try {
      const response = await fetch(`/api/phone-numbers/${phoneNumber.id}/assign`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          assistant_id: assistantId || null,
        }),
      });

      if (response.ok) {
        notify.success("Assistant assigned successfully");
        onUpdate();
      } else {
        const error = await response.json();
        notify.error(`Failed to assign: ${error.detail}`);
      }
    } catch (error) {
      console.error("Failed to assign phone number:", error);
      notify.error("Failed to assign phone number");
    } finally {
      setAssigning(false);
    }
  };

  const handleSmsToggle = async (enabled: boolean) => {
    setTogglingSms(true);
    try {
      const response = await fetch(`/api/phone-numbers/${phoneNumber.id}/sms-config`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          hotel_id: phoneNumber.hotel_id,
          sms_enabled: enabled,
          sms_assistant_id: phoneNumber.sms_assistant_id || null,
        }),
      });

      if (response.ok) {
        notify.success(enabled ? "SMS enabled" : "SMS disabled");
        onUpdate();
      } else {
        const error = await response.json();
        notify.error(`Failed to update SMS: ${error.detail}`);
      }
    } catch (error) {
      console.error("Failed to toggle SMS:", error);
      notify.error("Failed to update SMS config");
    } finally {
      setTogglingSms(false);
    }
  };

  const handleSmsAssistantChange = async (assistantId: string) => {
    setTogglingSms(true);
    try {
      const response = await fetch(`/api/phone-numbers/${phoneNumber.id}/sms-config`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          hotel_id: phoneNumber.hotel_id,
          sms_enabled: phoneNumber.sms_enabled || false,
          sms_assistant_id: assistantId || null,
        }),
      });

      if (response.ok) {
        notify.success("SMS assistant updated");
        onUpdate();
      } else {
        const error = await response.json();
        notify.error(`Failed to update: ${error.detail}`);
      }
    } catch (error) {
      console.error("Failed to update SMS assistant:", error);
      notify.error("Failed to update SMS assistant");
    } finally {
      setTogglingSms(false);
    }
  };

  return (
    <div className="bg-[#141414] border border-gray-800 rounded-lg p-4 hover:border-gray-700 transition-colors">
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center space-x-3">
          <div className="w-10 h-10 bg-blue-600/10 rounded-lg flex items-center justify-center">
            <Phone className="h-5 w-5 text-blue-500" />
          </div>
          <div>
            <div className="text-white font-medium">{phoneNumber.phone_number}</div>
            {phoneNumber.friendly_name && (
              <div className="text-sm text-gray-400">{phoneNumber.friendly_name}</div>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {phoneNumber.sms_enabled && (
            <div className="flex items-center gap-1 px-2 py-0.5 bg-indigo-600/10 rounded text-xs text-indigo-400">
              <MessageSquare className="h-3 w-3" />
              SMS
            </div>
          )}
          {phoneNumber.is_active && (
            <div className="w-2 h-2 bg-green-500 rounded-full"></div>
          )}
        </div>
      </div>

      <div className="space-y-3 mb-4">
        <div className="text-sm text-gray-400">
          Country: <span className="text-gray-300">{phoneNumber.country_code}</span>
        </div>

        <div>
          <div className="text-sm text-gray-400 mb-1">Voice Assistant:</div>
          <select
            value={phoneNumber.assistant_id || ""}
            onChange={(e) => handleAssignment(e.target.value)}
            disabled={assigning}
            className="w-full px-3 py-2 bg-[#1a1a1a] border border-gray-700 rounded-lg text-sm text-gray-300 focus:outline-none focus:border-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <option value="">Not assigned</option>
            {assistants && assistants.length > 0 ? (
              assistants.map((assistant) => (
                <option key={assistant.id} value={assistant.id}>
                  {assistant.name}
                </option>
              ))
            ) : (
              <option disabled>No assistants available</option>
            )}
          </select>
        </div>

        <div className="border-t border-gray-800 pt-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm text-gray-400">SMS</span>
            <label className="relative inline-flex items-center cursor-pointer">
              <input
                type="checkbox"
                checked={phoneNumber.sms_enabled || false}
                onChange={(e) => handleSmsToggle(e.target.checked)}
                disabled={toggingSms}
                className="sr-only peer"
              />
              <div className="w-9 h-5 bg-[#2a2a2a] peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-indigo-600 peer-disabled:opacity-50"></div>
            </label>
          </div>
          {phoneNumber.sms_enabled && (
            <div>
              <div className="text-xs text-gray-500 mb-1">SMS Assistant (optional, defaults to voice):</div>
              <select
                value={phoneNumber.sms_assistant_id || ""}
                onChange={(e) => handleSmsAssistantChange(e.target.value)}
                disabled={toggingSms}
                className="w-full px-3 py-1.5 bg-[#1a1a1a] border border-gray-700 rounded-lg text-xs text-gray-300 focus:outline-none focus:border-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <option value="">Same as voice assistant</option>
                {assistants && assistants.length > 0 ? (
                  assistants.map((assistant) => (
                    <option key={assistant.id} value={assistant.id}>
                      {assistant.name}
                    </option>
                  ))
                ) : (
                  <option disabled>No assistants available</option>
                )}
              </select>
            </div>
          )}
        </div>
      </div>

      <div className="flex items-center space-x-2">
        <button
          onClick={() => onDelete(phoneNumber.id)}
          className="flex-1 flex items-center justify-center space-x-2 px-3 py-2 bg-red-600/10 hover:bg-red-600/20 text-red-500 rounded-lg transition-colors text-sm"
        >
          <Trash2 className="h-4 w-4" />
          <span>Delete</span>
        </button>
      </div>
    </div>
  );
}
