"use client";

import { useState, useEffect } from "react";
import { Phone, Trash2 } from "lucide-react";

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
    is_active: boolean;
  };
  onDelete: (id: string) => void;
  onUpdate: () => void;
}

export default function PhoneNumberCard({ phoneNumber, onDelete, onUpdate }: PhoneNumberCardProps) {
  const [assistants, setAssistants] = useState<Assistant[]>([]);
  const [assigning, setAssigning] = useState(false);

  useEffect(() => {
    fetchAssistants();
  }, []);

  const fetchAssistants = async () => {
    try {
      const hotelId = "6b410bcc-f843-40df-b32d-078d3e01ac7f"; // Demo Hotel ID
      const response = await fetch(`/api/assistants?hotel_id=${hotelId}`);
      const data = await response.json();
      setAssistants(data.assistants || []);
    } catch (error) {
      console.error("Failed to fetch assistants:", error);
    }
  };

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
        onUpdate();
      } else {
        const error = await response.json();
        alert(`Failed to assign: ${error.detail}`);
      }
    } catch (error) {
      console.error("Failed to assign phone number:", error);
      alert("Failed to assign phone number");
    } finally {
      setAssigning(false);
    }
  };

  const getAssistantName = () => {
    if (!phoneNumber.assistant_id) return "Not assigned";
    const assistant = assistants.find(a => a.id === phoneNumber.assistant_id);
    return assistant?.name || "Unknown";
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
        {phoneNumber.is_active && (
          <div className="w-2 h-2 bg-green-500 rounded-full"></div>
        )}
      </div>

      <div className="space-y-2 mb-4">
        <div className="text-sm text-gray-400">
          Country: <span className="text-gray-300">{phoneNumber.country_code}</span>
        </div>
        <div className="text-sm text-gray-400 mb-1">Assistant:</div>
        <select
          value={phoneNumber.assistant_id || ""}
          onChange={(e) => handleAssignment(e.target.value)}
          disabled={assigning}
          className="w-full px-3 py-2 bg-[#1a1a1a] border border-gray-700 rounded-lg text-sm text-gray-300 focus:outline-none focus:border-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <option value="">Not assigned</option>
          {assistants.map((assistant) => (
            <option key={assistant.id} value={assistant.id}>
              {assistant.name}
            </option>
          ))}
        </select>
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
