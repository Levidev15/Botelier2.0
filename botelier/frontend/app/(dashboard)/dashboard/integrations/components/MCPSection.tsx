"use client";

import { Server, Plus } from "lucide-react";
import type { MCPConnection } from "../types";
import MCPConnectionCard from "./MCPConnectionCard";

interface MCPSectionProps {
  mcpConnections: MCPConnection[];
  testingMcp: string | null;
  onCreateMcp: () => void;
  onTestMcp: (mcp: MCPConnection) => void;
  onEditMcp: (mcp: MCPConnection) => void;
  onDeleteMcp: (mcp: MCPConnection) => void;
}

export default function MCPSection({ mcpConnections, testingMcp, onCreateMcp, onTestMcp, onEditMcp, onDeleteMcp }: MCPSectionProps) {
  return (
    <div className="mt-10">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-xl font-bold flex items-center gap-2">
            <Server className="h-5 w-5" />
            MCP Connections
          </h2>
          <p className="text-sm text-gray-400 mt-1">
            Connect to external MCP servers to enable dynamic tools for your assistants
          </p>
        </div>
        <button
          onClick={onCreateMcp}
          className="inline-flex items-center px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition"
        >
          <Plus className="h-4 w-4 mr-2" />
          Add Connection
        </button>
      </div>

      <div className="space-y-4">
        {mcpConnections.map((mcp) => (
          <MCPConnectionCard
            key={mcp.id}
            mcp={mcp}
            testingMcp={testingMcp}
            handleTestMcp={onTestMcp}
            handleEditMcp={onEditMcp}
            handleDeleteMcp={onDeleteMcp}
          />
        ))}
        {mcpConnections.length === 0 && (
          <div className="bg-[#141414] border border-gray-800 rounded-lg p-12 text-center">
            <Server className="h-12 w-12 text-gray-600 mx-auto mb-4" />
            <p className="text-gray-400 mb-2">No MCP connections yet</p>
            <p className="text-sm text-gray-500">
              Connect to an MCP server to provide external tools for your voice assistants
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
