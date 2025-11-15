import { Plus, Phone } from "lucide-react";

export default function PhoneNumbersPage() {
  return (
    <div className="p-8">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h1 className="text-2xl font-bold">Phone Numbers</h1>
          <p className="text-sm text-gray-400 mt-1">
            Manage your Twilio phone numbers
          </p>
        </div>
        <button className="inline-flex items-center px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg transition text-sm font-medium">
          <Plus className="h-4 w-4 mr-2" />
          Add Number
        </button>
      </div>

      <div className="bg-[#141414] border border-gray-800 rounded-lg p-12 text-center">
        <Phone className="h-12 w-12 text-gray-600 mx-auto mb-4" />
        <h3 className="text-lg font-semibold mb-2">No phone numbers yet</h3>
        <p className="text-sm text-gray-400 mb-6">
          Add a phone number to start receiving calls
        </p>
        <button className="inline-flex items-center px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg transition text-sm font-medium">
          <Plus className="h-4 w-4 mr-2" />
          Add Your First Number
        </button>
      </div>
    </div>
  );
}
