import { Plus, Key, Eye, EyeOff, Copy } from "lucide-react";

export default function APIKeysPage() {
  return (
    <div className="p-8">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h1 className="text-2xl font-bold">API Keys</h1>
          <p className="text-sm text-gray-400 mt-1">
            Manage your provider API keys
          </p>
        </div>
        <button className="inline-flex items-center px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg transition text-sm font-medium">
          <Plus className="h-4 w-4 mr-2" />
          Add API Key
        </button>
      </div>

      <div className="space-y-4">
        <div className="bg-[#141414] border border-gray-800 rounded-lg p-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-4">
              <div className="w-10 h-10 bg-blue-600/10 rounded-lg flex items-center justify-center">
                <Key className="h-5 w-5 text-blue-400" />
              </div>
              <div>
                <h3 className="font-semibold">OpenAI API Key</h3>
                <p className="text-sm text-gray-400 mt-0.5">sk-proj-••••••••••••</p>
              </div>
            </div>
            <div className="flex items-center space-x-2">
              <button className="p-2 hover:bg-gray-800 rounded-lg transition">
                <Eye className="h-4 w-4 text-gray-400" />
              </button>
              <button className="p-2 hover:bg-gray-800 rounded-lg transition">
                <Copy className="h-4 w-4 text-gray-400" />
              </button>
            </div>
          </div>
        </div>

        <div className="bg-[#141414] border border-gray-800 rounded-lg p-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-4">
              <div className="w-10 h-10 bg-purple-600/10 rounded-lg flex items-center justify-center">
                <Key className="h-5 w-5 text-purple-400" />
              </div>
              <div>
                <h3 className="font-semibold">Deepgram API Key</h3>
                <p className="text-sm text-gray-400 mt-0.5">••••••••••••••••</p>
              </div>
            </div>
            <div className="flex items-center space-x-2">
              <button className="p-2 hover:bg-gray-800 rounded-lg transition">
                <Eye className="h-4 w-4 text-gray-400" />
              </button>
              <button className="p-2 hover:bg-gray-800 rounded-lg transition">
                <Copy className="h-4 w-4 text-gray-400" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
