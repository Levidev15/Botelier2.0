import { ArrowLeft, Save, Play } from "lucide-react";
import Link from "next/link";

export default function AssistantDetailPage({ params }: { params: { id: string } }) {
  return (
    <div className="h-full overflow-auto">
      <div className="border-b border-gray-800 bg-[#0a0a0a] sticky top-0 z-10">
        <div className="px-8 py-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-4">
              <Link
                href="/dashboard/assistants"
                className="p-2 hover:bg-gray-800 rounded-lg transition"
              >
                <ArrowLeft className="h-5 w-5" />
              </Link>
              <div>
                <h1 className="text-2xl font-bold">Hotel Concierge</h1>
                <p className="text-sm text-gray-400 mt-1">
                  Configure assistant settings
                </p>
              </div>
            </div>
            <div className="flex items-center space-x-3">
              <button className="inline-flex items-center px-4 py-2 bg-green-600 hover:bg-green-700 rounded-lg transition text-sm font-medium">
                <Play className="h-4 w-4 mr-2" />
                Test
              </button>
              <button className="inline-flex items-center px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg transition text-sm font-medium">
                <Save className="h-4 w-4 mr-2" />
                Save
              </button>
            </div>
          </div>
        </div>
      </div>

      <div className="p-8 max-w-4xl">
        <div className="bg-[#141414] border border-gray-800 rounded-lg p-6">
          <h2 className="text-lg font-semibold mb-4">Model Configuration</h2>
          <p className="text-sm text-gray-400">
            Model: gpt-4o-mini • Voice: British Reading Lady • Language: English
          </p>
        </div>
      </div>
    </div>
  );
}
