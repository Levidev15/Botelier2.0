"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Loader2,
  AlertCircle,
  Upload,
  Plus,
  Settings,
  Zap,
  ChevronDown,
  ChevronRight,
  CheckCircle,
  XCircle,
} from "lucide-react";
import type {
  ImportableIntegrationType,
  AccountIntegration,
  IntegrationType,
} from "../types";
import ImportSpecModal from "./ImportSpecModal";
import ConnectModal from "./ConnectModal";
import OperationCatalogPanel from "./OperationCatalogPanel";

interface APIBuilderSectionProps {
  accountId: string;
  authFetch: (url: string, options?: RequestInit) => Promise<Response>;
  onNotify: (type: "success" | "error", message: string) => void;
  canManage: boolean;
}

const SOURCE_LABEL: Record<string, string> = {
  openapi: "OpenAPI",
  swagger: "Swagger",
  postman: "Postman",
};

export default function APIBuilderSection({
  accountId,
  authFetch,
  onNotify,
  canManage,
}: APIBuilderSectionProps) {
  const [importedTypes, setImportedTypes] = useState<ImportableIntegrationType[]>([]);
  const [connections, setConnections] = useState<AccountIntegration[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [showImportModal, setShowImportModal] = useState(false);

  // For adding a connection to an imported type
  const [connectingType, setConnectingType] = useState<ImportableIntegrationType | null>(null);

  // For viewing operations on a connection
  const [catalogConn, setCatalogConn] = useState<{
    connectionId: string;
    connectionName: string;
    integrationName: string;
  } | null>(null);

  // Expanded type cards
  const [expandedTypeId, setExpandedTypeId] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [typesRes, connRes] = await Promise.all([
        authFetch(`/api/integrations/types/importable?account_id=${accountId}`),
        authFetch(`/api/integrations/account/${accountId}`),
      ]);
      if (typesRes.ok) {
        const data = await typesRes.json();
        setImportedTypes(data.integration_types || []);
      } else {
        const data = await typesRes.json().catch(() => ({}));
        setLoadError(data.detail || "Failed to load imported integrations");
      }
      if (connRes.ok) {
        const data = await connRes.json();
        setConnections(data || []);
      }
    } catch (err: any) {
      setLoadError(err?.message || "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [accountId]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const getTypeConnections = (typeId: string) =>
    connections.filter((c) => c.integration_type_id === typeId);

  // Default required_fields for imported types that have none set (e.g. unauthenticated APIs).
  const FALLBACK_REQUIRED_FIELDS = [
    {
      key: "base_url",
      label: "Base URL",
      type: "text",
      placeholder: "https://api.example.com/v1",
      required: false,
      description: "Override the base URL from the spec for this connection",
    },
  ];

  // Build a minimal IntegrationType shape for ConnectModal from an importable type.
  // Uses the actual auth_type and required_fields stored by the spec importer so
  // ConnectModal shows the right credential fields for each API's auth scheme.
  const buildConnectType = (it: ImportableIntegrationType): IntegrationType => ({
    id: it.id,
    slug: it.slug,
    name: it.name,
    description: "",
    logo_url: null,
    provider: "custom",
    auth_type: it.auth_type || "api_key",
    documentation_url: null,
    is_enabled: true,
    required_fields:
      it.required_fields && it.required_fields.length > 0
        ? it.required_fields
        : FALLBACK_REQUIRED_FIELDS,
    endpoint_count: it.endpoint_count,
  });

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Section header */}
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-base font-semibold flex items-center gap-2">
            <Zap className="h-4 w-4 text-blue-400" />
            Universal API Adapter
          </h2>
          <p className="text-sm text-gray-400 mt-1">
            Import any REST API spec (OpenAPI / Swagger / Postman), then configure
            and publish individual operations as AI tools — no code required.
          </p>
        </div>
        {canManage && (
          <button
            onClick={() => setShowImportModal(true)}
            className="inline-flex items-center gap-2 px-3 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition flex-shrink-0"
          >
            <Upload className="h-4 w-4" />
            Import Spec
          </button>
        )}
      </div>

      {loadError && (
        <div className="flex items-start gap-2 p-3 bg-red-900/20 border border-red-800 rounded-lg text-sm text-red-300">
          <AlertCircle className="h-4 w-4 flex-shrink-0 mt-0.5" />
          <span>{loadError}</span>
        </div>
      )}

      {/* Imported integration types */}
      {importedTypes.length === 0 ? (
        <div className="border-2 border-dashed border-gray-800 rounded-xl p-12 text-center">
          <Upload className="h-10 w-10 text-gray-600 mx-auto mb-3" />
          <p className="text-gray-400 font-medium">No API specs imported yet</p>
          <p className="text-sm text-gray-600 mt-1 max-w-xs mx-auto">
            Import an OpenAPI, Swagger, or Postman spec to turn any REST API into
            configurable AI tools.
          </p>
          {canManage && (
            <button
              onClick={() => setShowImportModal(true)}
              className="mt-4 inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition"
            >
              <Upload className="h-4 w-4" />
              Import Your First Spec
            </button>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          {importedTypes.map((it) => {
            const typeConns = getTypeConnections(it.id);
            const isExpanded = expandedTypeId === it.id;

            return (
              <div
                key={it.id}
                className="rounded-xl border border-gray-800 bg-[#141414] overflow-hidden"
              >
                {/* Type card header */}
                <div
                  className="flex items-center gap-4 px-5 py-4 cursor-pointer hover:bg-[#181818] transition-colors"
                  onClick={() =>
                    setExpandedTypeId(isExpanded ? null : it.id)
                  }
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-medium text-sm">{it.name}</span>
                      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs border bg-gray-800/60 text-gray-400 border-gray-700">
                        {SOURCE_LABEL[it.source_type] || it.source_type}
                      </span>
                      <span className="text-xs text-gray-500">
                        {it.endpoint_count} endpoint
                        {it.endpoint_count !== 1 ? "s" : ""}
                      </span>
                    </div>
                    <p className="text-xs text-gray-500 mt-0.5">
                      {typeConns.length} connection
                      {typeConns.length !== 1 ? "s" : ""}
                      {typeConns.filter((c) => c.status === "connected").length > 0 &&
                        ` · ${
                          typeConns.filter((c) => c.status === "connected").length
                        } connected`}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    {canManage && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setConnectingType(it);
                        }}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-white bg-gray-700 hover:bg-gray-600 rounded-lg transition"
                      >
                        <Plus className="h-3.5 w-3.5" />
                        Add Connection
                      </button>
                    )}
                    {isExpanded ? (
                      <ChevronDown className="h-4 w-4 text-gray-500" />
                    ) : (
                      <ChevronRight className="h-4 w-4 text-gray-500" />
                    )}
                  </div>
                </div>

                {/* Connections list */}
                {isExpanded && (
                  <div className="border-t border-gray-800">
                    {typeConns.length === 0 ? (
                      <div className="px-5 py-6 text-center text-sm text-gray-500">
                        No connections yet.{" "}
                        {canManage && (
                          <button
                            onClick={() => setConnectingType(it)}
                            className="text-blue-400 hover:text-blue-300"
                          >
                            Add a connection
                          </button>
                        )}{" "}
                        to start configuring operations.
                      </div>
                    ) : (
                      <div className="divide-y divide-gray-800/60">
                        {typeConns.map((conn) => (
                          <div
                            key={conn.id}
                            className="flex items-center gap-4 px-5 py-3"
                          >
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2">
                                {conn.status === "connected" ? (
                                  <CheckCircle className="h-3.5 w-3.5 text-green-400 flex-shrink-0" />
                                ) : (
                                  <XCircle className="h-3.5 w-3.5 text-gray-600 flex-shrink-0" />
                                )}
                                <span className="text-sm font-medium truncate">
                                  {conn.connection_name || conn.integration_name}
                                </span>
                                <span
                                  className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] border ${
                                    conn.status === "connected"
                                      ? "bg-green-900/30 text-green-300 border-green-800"
                                      : "bg-gray-800/40 text-gray-400 border-gray-700"
                                  }`}
                                >
                                  {conn.status}
                                </span>
                              </div>
                              {conn.last_error && (
                                <p className="text-xs text-red-400 mt-0.5 truncate">
                                  {conn.last_error}
                                </p>
                              )}
                            </div>
                            <button
                              onClick={() =>
                                setCatalogConn({
                                  connectionId: conn.id,
                                  connectionName:
                                    conn.connection_name || conn.integration_name,
                                  integrationName: it.name,
                                })
                              }
                              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-white bg-blue-700 hover:bg-blue-600 rounded-lg transition flex-shrink-0"
                            >
                              <Settings className="h-3.5 w-3.5" />
                              Configure Operations
                            </button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Import spec modal */}
      {showImportModal && (
        <ImportSpecModal
          accountId={accountId}
          authFetch={authFetch}
          onSuccess={fetchData}
          onNotify={onNotify}
          onClose={() => setShowImportModal(false)}
        />
      )}

      {/* Connect modal for imported type */}
      {connectingType && (
        <ConnectModal
          selectedType={buildConnectType(connectingType)}
          accountId={accountId}
          authFetch={authFetch}
          onSuccess={fetchData}
          onNotify={onNotify}
          onClose={() => setConnectingType(null)}
        />
      )}

      {/* Operation catalog panel */}
      {catalogConn && (
        <OperationCatalogPanel
          accountId={accountId}
          connectionId={catalogConn.connectionId}
          connectionName={catalogConn.connectionName}
          integrationName={catalogConn.integrationName}
          authFetch={authFetch}
          onNotify={onNotify}
          onClose={() => setCatalogConn(null)}
        />
      )}
    </div>
  );
}
