"use client";

import {
  Plug, AlertCircle, ExternalLink, RefreshCw, Loader2, Trash2, Plus,
} from "lucide-react";
import type { IntegrationType, AccountIntegration, IntegrationStats } from "../types";

function getStatusBadge(status: string) {
  switch (status) {
    case "connected":
      return (
        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-900/50 text-green-400 border border-green-700">
          <span className="w-2 h-2 rounded-full bg-green-400 mr-1.5 animate-pulse" />
          Connected
        </span>
      );
    case "error":
      return (
        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-900/50 text-red-400 border border-red-700">
          <span className="w-2 h-2 rounded-full bg-red-400 mr-1.5" />
          Error
        </span>
      );
    case "token_expired":
      return (
        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-amber-900/50 text-amber-400 border border-amber-700">
          <AlertCircle className="h-3 w-3 mr-1" />
          Token Expired
        </span>
      );
    case "connecting":
      return (
        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-yellow-900/50 text-yellow-400 border border-yellow-700">
          <Loader2 className="h-3 w-3 mr-1 animate-spin" />
          Connecting
        </span>
      );
    case "disconnected":
      return (
        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-800 text-gray-400 border border-gray-700">
          <span className="w-2 h-2 rounded-full bg-gray-500 mr-1.5" />
          Disconnected
        </span>
      );
    default:
      return (
        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-800 text-gray-400 border border-gray-700">
          {status.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())}
        </span>
      );
  }
}

interface IntegrationCardProps {
  type: IntegrationType;
  connections: AccountIntegration[];
  integrationStats: Record<string, IntegrationStats>;
  testing: string | null;
  handleConnect: (type: IntegrationType) => void;
  handleTestConnection: (conn: AccountIntegration) => void;
  handleDisconnect: (conn: AccountIntegration) => void;
}

export default function IntegrationCard({
  type,
  connections,
  integrationStats,
  testing,
  handleConnect,
  handleTestConnection,
  handleDisconnect,
}: IntegrationCardProps) {
  const slugInitials = type.slug === "opera-cloud" ? "OC" : type.slug === "guestcentric-crs" ? "GC" : type.name.slice(0, 2).toUpperCase();
  const gradientClass = type.slug === "opera-cloud" ? "from-orange-500 to-red-600" : "from-emerald-500 to-teal-600";

  return (
    <div className="bg-[#141414] border border-gray-800 rounded-lg p-6 hover:border-gray-700 transition">
      <div className="flex items-start justify-between">
        <div className="flex items-start gap-4">
          <div className={`w-12 h-12 bg-gradient-to-br ${gradientClass} rounded-lg flex items-center justify-center text-white font-bold text-lg`}>
            {slugInitials}
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-lg font-semibold">{type.name}</h3>
              {type.endpoint_count > 0 && (
                <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-800 text-gray-400 border border-gray-700">
                  {type.endpoint_count} endpoint{type.endpoint_count !== 1 ? "s" : ""}
                </span>
              )}
            </div>
            <p className="text-sm text-gray-400 mt-1 max-w-lg">{type.description}</p>
            {type.documentation_url && (
              <a
                href={type.documentation_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center text-xs text-blue-400 hover:text-blue-300 mt-2"
              >
                View Documentation
                <ExternalLink className="h-3 w-3 ml-1" />
              </a>
            )}
          </div>
        </div>

        <button
          onClick={() => handleConnect(type)}
          className="inline-flex items-center px-4 py-1.5 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition"
        >
          <Plus className="h-4 w-4 mr-1" />
          Add Connection
        </button>
      </div>

      {connections.length > 0 && (
        <div className="mt-4 space-y-2 border-t border-gray-800 pt-4">
          {connections.map((conn) => (
            <div
              key={conn.id}
              className="flex items-center justify-between bg-[#0a0a0a] border border-gray-800 rounded-lg px-4 py-3"
            >
              <div className="flex items-center gap-3">
                <Plug className="h-4 w-4 text-gray-500" />
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{conn.connection_name || conn.integration_name}</span>
                    {getStatusBadge(conn.status)}
                  </div>
                  {conn.last_error && (
                    <p className="text-xs text-red-400 mt-0.5">{conn.last_error}</p>
                  )}
                  {integrationStats[conn.id] && (() => {
                    const s = integrationStats[conn.id];
                    return (
                      <div className="flex items-center gap-3 mt-1.5">
                        <span className="text-xs text-gray-500">
                          <span className="text-green-400 font-medium">{s.successful_calls}</span>/{s.total_calls} calls OK
                        </span>
                        {s.failed_calls > 0 && (
                          <span className="text-xs text-red-400">{s.failed_calls} failed</span>
                        )}
                        {s.last_called_at && (
                          <span className="text-xs text-gray-600">
                            Last: {new Date(s.last_called_at).toLocaleDateString()}
                          </span>
                        )}
                        {s.last_error && (
                          <span className="text-xs text-red-400 truncate max-w-[200px]" title={s.last_error}>
                            {s.last_error}
                          </span>
                        )}
                      </div>
                    );
                  })()}
                  {conn.connected_at && (
                    <p className="text-xs text-gray-500 mt-0.5">
                      Connected {new Date(conn.connected_at).toLocaleDateString()}
                    </p>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => handleTestConnection(conn)}
                  disabled={testing === conn.id}
                  className="px-2.5 py-1 text-sm text-gray-300 bg-gray-800 hover:bg-gray-700 rounded-lg transition disabled:opacity-50"
                  title="Test connection"
                >
                  {testing === conn.id ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <RefreshCw className="h-3.5 w-3.5" />
                  )}
                </button>
                <button
                  onClick={() => handleDisconnect(conn)}
                  className="px-2.5 py-1 text-sm text-red-400 hover:text-red-300 bg-gray-800 hover:bg-gray-700 rounded-lg transition"
                  title="Remove connection"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
