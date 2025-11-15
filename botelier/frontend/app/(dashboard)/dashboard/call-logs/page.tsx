import { BarChart, Download } from "lucide-react";

export default function CallLogsPage() {
  return (
    <div className="p-8">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h1 className="text-2xl font-bold">Call Logs</h1>
          <p className="text-sm text-gray-400 mt-1">
            View and analyze call history
          </p>
        </div>
        <button className="inline-flex items-center px-4 py-2 bg-[#141414] border border-gray-800 hover:bg-gray-800 rounded-lg transition text-sm font-medium">
          <Download className="h-4 w-4 mr-2" />
          Export
        </button>
      </div>

      <div className="bg-[#141414] border border-gray-800 rounded-lg p-12 text-center">
        <BarChart className="h-12 w-12 text-gray-600 mx-auto mb-4" />
        <h3 className="text-lg font-semibold mb-2">No calls yet</h3>
        <p className="text-sm text-gray-400">
          Call logs will appear here once you start receiving calls
        </p>
      </div>
    </div>
  );
}
