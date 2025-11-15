import { Save } from "lucide-react";

export default function SettingsPage() {
  return (
    <div className="p-8 max-w-3xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold">Settings</h1>
        <p className="text-sm text-gray-400 mt-1">
          Manage your account settings
        </p>
      </div>

      <div className="space-y-6">
        <div className="bg-[#141414] border border-gray-800 rounded-lg p-6">
          <h2 className="text-lg font-semibold mb-4">Hotel Information</h2>
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-2">
                Hotel Name
              </label>
              <input
                type="text"
                defaultValue="Hotel Demo"
                className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-2">
                Email
              </label>
              <input
                type="email"
                defaultValue="hotel@example.com"
                className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
              />
            </div>
          </div>
        </div>

        <div className="bg-[#141414] border border-gray-800 rounded-lg p-6">
          <h2 className="text-lg font-semibold mb-4">Billing</h2>
          <p className="text-sm text-gray-400">
            Manage your subscription and billing information
          </p>
          <button className="mt-4 px-4 py-2 bg-gray-800 hover:bg-gray-700 rounded-lg transition text-sm font-medium">
            Manage Subscription
          </button>
        </div>

        <div className="flex justify-end">
          <button className="inline-flex items-center px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg transition text-sm font-medium">
            <Save className="h-4 w-4 mr-2" />
            Save Changes
          </button>
        </div>
      </div>
    </div>
  );
}
