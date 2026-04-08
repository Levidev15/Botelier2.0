"use client";

import { Check, AlertCircle, Loader2, RefreshCw, Pencil, Trash2, Server, Wrench } from "lucide-react";
import type { MCPConnection } from "../types";

function getMcpStatusBadge(status: string) {
  switch (status) {
    case "connected":
      return (
        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-900/50 text-green-400 border border-green-700">
          <Check className="h-3 w-3 mr-1" />
          Connected
        </span>
      );
    case "error":
      return (
        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-900/50 text-red-400 border border-red-700">
          <AlertCircle className="h-3 w-3 mr-1" />
          Error
        </span>
      );
    case "connecting":
      return (
        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-yellow-900/50 text-yellow-400 border border-yellow-700">
          <Loader2 className="h-3 w-3 mr-1 animate-spin" />
          Connecting
        </span>
      );
    default:
      return (
        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-800 text-gray-400 border border-gray-700">
          Not Tested
        </span>
      );
  }
}

interface MCPConnectionCardProps {
  mcp: MCPConnection;
  testingMcp: string | null;
  handleTestMcp: (mcp: MCPConnection) => void;
  handleEditMcp: (mcp: MCPConnection) => void;
  handleDeleteMcp: (mcp: MCPConnection) => void;
}

export default function MCPConnectionCard({
  mcp,
  testingMcp,
  handleTestMcp,
  handleEditMcp,
  handleDeleteMcp,
}: MCPConnectionCardProps) {
  return (
    <div className="bg-[#141414] border border-gray-800 rounded-lg p-6 hover:border-gray-700 transition">
      <div className="flex items-start justify-between">
        <div className="flex items-start gap-4">
          <div className="w-12 h-12 bg-gradient-to-br from-purple-500 to-blue-600 rounded-lg flex items-center justify-center text-white">
            <Server className="h-6 w-6" />
          </div>
          <div>
            <div className="flex items-center gap-3">
              <h3 className="text-lg font-semibold">{mcp.name}</h3>
              {getMcpStatusBadge(mcp.status)}
              {!mcp.is_active && (
                <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-800 text-gray-500">
                  Inactive
                </span>
              )}
            </div>
            {mcp.description && (
              <p className="text-sm text-gray-400 mt-1">{mcp.description}</p>
            )}
            <p className="text-xs text-gray-500 mt-2 font-mono">{mcp.server_url}</p>
            {mcp.last_error && (
              <p className="text-xs text-red-400 mt-1">Error: {mcp.last_error}</p>
            )}
            {mcp.discovered_tools && mcp.discovered_tools.length > 0 && (
              <div className="mt-3">
                <p className="text-xs text-gray-500 mb-1 flex items-center gap-1">
                  <Wrench className="h-3 w-3" />
                  {mcp.discovered_tools.length} tool{mcp.discovered_tools.length !== 1 ? "s" : ""} available
                </p>
                <div className="flex flex-wrap gap-1">
                  {mcp.discovered_tools.slice(0, 5).map((tool) => (
                    <span
                      key={tool.name}
                      className="px-2 py-0.5 text-xs bg-gray-800 text-gray-300 rounded"
                      title={tool.description}
                    >
                      {tool.name}
                    </span>
                  ))}
                  {mcp.discovered_tools.length > 5 && (
                    <span className="px-2 py-0.5 text-xs text-gray-500">
                      +{mcp.discovered_tools.length - 5} more
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => handleTestMcp(mcp)}
            disabled={testingMcp === mcp.id}
            className="p-2 text-gray-400 hover:text-white hover:bg-gray-800 rounded-lg transition disabled:opacity-50"
            title="Test Connection"
          >
            {testingMcp === mcp.id ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
          </button>
          <button
            onClick={() => handleEditMcp(mcp)}
            className="p-2 text-gray-400 hover:text-white hover:bg-gray-800 rounded-lg transition"
            title="Edit"
          >
            <Pencil className="h-4 w-4" />
          </button>
          <button
            onClick={() => handleDeleteMcp(mcp)}
            className="p-2 text-gray-400 hover:text-red-400 hover:bg-gray-800 rounded-lg transition"
            title="Delete"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
