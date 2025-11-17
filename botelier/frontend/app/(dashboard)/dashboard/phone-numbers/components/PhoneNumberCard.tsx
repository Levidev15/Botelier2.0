import { Phone, Trash2 } from "lucide-react";

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
        <div className="text-sm text-gray-400">
          Assistant: <span className="text-gray-300">{phoneNumber.assistant_id ? "Assigned" : "Not assigned"}</span>
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
