"use client";

import { useState, useEffect } from "react";
import { X, ChevronDown, ChevronRight, Shield } from "lucide-react";
import { toast } from "sonner";

const PERMISSION_SCHEMA = [
  {
    key: "assistants",
    label: "Assistants",
    description: "Voice AI assistant management",
    permissions: [
      { key: "view", label: "View assistants" },
      { key: "create", label: "Create assistants" },
      { key: "edit", label: "Edit configurations" },
      { key: "delete", label: "Delete assistants" },
      { key: "publish", label: "Publish flow changes" },
    ],
  },
  {
    key: "phone_numbers",
    label: "Phone Numbers",
    description: "Twilio number management",
    permissions: [
      { key: "view", label: "View phone numbers" },
      { key: "purchase", label: "Purchase numbers" },
      { key: "configure", label: "Configure settings" },
      { key: "release", label: "Release numbers" },
    ],
  },
  {
    key: "call_logs",
    label: "Call Logs",
    description: "Call history and transcripts",
    permissions: [
      { key: "view", label: "View call logs" },
      { key: "view_transcripts", label: "View transcripts" },
      { key: "export", label: "Export to CSV" },
      { key: "delete", label: "Delete logs" },
    ],
  },
  {
    key: "knowledge_base",
    label: "Knowledge Base",
    description: "AI knowledge management",
    permissions: [
      { key: "view", label: "View entries" },
      { key: "create", label: "Create entries" },
      { key: "edit", label: "Edit entries" },
      { key: "delete", label: "Delete entries" },
      { key: "import", label: "Bulk import" },
    ],
  },
  {
    key: "tools",
    label: "Tools",
    description: "Function calling tools",
    permissions: [
      { key: "view", label: "View tools" },
      { key: "create", label: "Create tools" },
      { key: "edit", label: "Edit tools" },
      { key: "delete", label: "Delete tools" },
    ],
  },
  {
    key: "flows",
    label: "Flows",
    description: "Conversation flow editor",
    permissions: [
      { key: "view", label: "View flows" },
      { key: "edit", label: "Edit flows" },
      { key: "publish", label: "Publish versions" },
      { key: "revert", label: "Revert versions" },
    ],
  },
  {
    key: "team",
    label: "Team",
    description: "Team management",
    permissions: [
      { key: "view", label: "View team members" },
      { key: "invite", label: "Invite members" },
      { key: "manage_roles", label: "Manage roles" },
      { key: "remove", label: "Remove members" },
    ],
  },
  {
    key: "settings",
    label: "Settings",
    description: "Account settings",
    permissions: [
      { key: "view", label: "View settings" },
      { key: "edit", label: "Edit settings" },
      { key: "billing", label: "Billing management" },
      { key: "api_keys", label: "API key management" },
    ],
  },
];

type PermissionsMap = Record<string, Record<string, boolean>>;

function buildEmptyPermissions(): PermissionsMap {
  const result: PermissionsMap = {};
  for (const feature of PERMISSION_SCHEMA) {
    result[feature.key] = {};
    for (const perm of feature.permissions) {
      result[feature.key][perm.key] = false;
    }
  }
  return result;
}

function mergePermissions(base: PermissionsMap, override: Record<string, unknown>): PermissionsMap {
  const result = buildEmptyPermissions();
  for (const feature of PERMISSION_SCHEMA) {
    const featurePerms = (override[feature.key] || {}) as Record<string, boolean>;
    for (const perm of feature.permissions) {
      result[feature.key][perm.key] = featurePerms[perm.key] === true;
    }
  }
  return result;
}

function countEnabledPermissions(permissions: PermissionsMap): { enabled: number; total: number } {
  let enabled = 0;
  let total = 0;
  for (const feature of PERMISSION_SCHEMA) {
    for (const perm of feature.permissions) {
      total++;
      if (permissions[feature.key]?.[perm.key]) enabled++;
    }
  }
  return { enabled, total };
}

interface RoleToEdit {
  id?: string;
  name?: string;
  description?: string | null;
  permissions?: Record<string, unknown>;
}

interface RoleEditorSlideOverProps {
  accountId: string;
  role?: RoleToEdit;
  onClose: () => void;
  onSuccess: () => void;
  authFetch: (url: string, options?: RequestInit) => Promise<Response>;
}

export default function RoleEditorSlideOver({
  accountId,
  role,
  onClose,
  onSuccess,
  authFetch,
}: RoleEditorSlideOverProps) {
  const isEditing = !!role?.id;

  const [name, setName] = useState(role?.name || "");
  const [description, setDescription] = useState(role?.description || "");
  const [permissions, setPermissions] = useState<PermissionsMap>(() =>
    mergePermissions(buildEmptyPermissions(), role?.permissions || {})
  );
  const [expandedFeatures, setExpandedFeatures] = useState<Set<string>>(
    new Set(PERMISSION_SCHEMA.map((f) => f.key))
  );
  const [loading, setLoading] = useState(false);

  const { enabled, total } = countEnabledPermissions(permissions);

  const toggleFeature = (featureKey: string) => {
    setExpandedFeatures((prev) => {
      const next = new Set(prev);
      if (next.has(featureKey)) next.delete(featureKey);
      else next.add(featureKey);
      return next;
    });
  };

  const togglePermission = (featureKey: string, permKey: string) => {
    setPermissions((prev) => ({
      ...prev,
      [featureKey]: {
        ...prev[featureKey],
        [permKey]: !prev[featureKey]?.[permKey],
      },
    }));
  };

  const toggleAllForFeature = (featureKey: string) => {
    const feature = PERMISSION_SCHEMA.find((f) => f.key === featureKey);
    if (!feature) return;

    const allEnabled = feature.permissions.every(
      (p) => permissions[featureKey]?.[p.key]
    );

    setPermissions((prev) => ({
      ...prev,
      [featureKey]: Object.fromEntries(
        feature.permissions.map((p) => [p.key, !allEnabled])
      ),
    }));
  };

  const isFeatureFullyEnabled = (featureKey: string): boolean => {
    const feature = PERMISSION_SCHEMA.find((f) => f.key === featureKey);
    if (!feature) return false;
    return feature.permissions.every((p) => permissions[featureKey]?.[p.key]);
  };

  const isFeaturePartiallyEnabled = (featureKey: string): boolean => {
    const feature = PERMISSION_SCHEMA.find((f) => f.key === featureKey);
    if (!feature) return false;
    const enabledCount = feature.permissions.filter(
      (p) => permissions[featureKey]?.[p.key]
    ).length;
    return enabledCount > 0 && enabledCount < feature.permissions.length;
  };

  const handleSubmit = async () => {
    if (!name.trim()) {
      toast.error("Role name is required");
      return;
    }

    setLoading(true);
    try {
      const url = isEditing
        ? `/api/accounts/${accountId}/team/roles/${role!.id}`
        : `/api/accounts/${accountId}/team/roles`;

      const res = await authFetch(url, {
        method: isEditing ? "PATCH" : "POST",
        body: JSON.stringify({
          name: name.trim(),
          description: description.trim() || null,
          permissions,
        }),
      });

      const data = await res.json();

      if (!res.ok) {
        toast.error(data.detail || "Failed to save role");
        return;
      }

      toast.success(isEditing ? "Role updated" : "Role created");
      onSuccess();
      onClose();
    } catch {
      toast.error("Failed to save role");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />

      <div className="relative w-full max-w-xl bg-[#111111] border-l border-[#222222] flex flex-col h-full shadow-2xl">
        <div className="flex items-center justify-between p-6 border-b border-[#222222] flex-shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-purple-600/10 rounded-lg flex items-center justify-center">
              <Shield className="w-4 h-4 text-purple-400" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-white">
                {isEditing ? "Edit Role" : "Create Custom Role"}
              </h2>
              <p className="text-xs text-gray-500">
                {enabled} of {total} permissions enabled
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-md hover:bg-[#222222] text-gray-400 hover:text-white transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-400 mb-1.5">
                Role Name <span className="text-red-400">*</span>
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Support Agent, Night Manager"
                maxLength={50}
                className="w-full px-3 py-2.5 bg-[#0a0a0a] border border-[#333333] rounded-lg text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 text-sm"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-400 mb-1.5">
                Description
              </label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Briefly describe what this role can do..."
                rows={2}
                className="w-full px-3 py-2.5 bg-[#0a0a0a] border border-[#333333] rounded-lg text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 text-sm resize-none"
              />
            </div>
          </div>

          <div>
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-white">Permissions</h3>
              <div className="flex items-center gap-2">
                <div className="h-1.5 bg-[#222222] rounded-full w-24 overflow-hidden">
                  <div
                    className="h-full bg-blue-500 rounded-full transition-all"
                    style={{ width: `${total > 0 ? (enabled / total) * 100 : 0}%` }}
                  />
                </div>
                <span className="text-xs text-gray-400">
                  {enabled}/{total}
                </span>
              </div>
            </div>

            <div className="space-y-2">
              {PERMISSION_SCHEMA.map((feature) => {
                const isExpanded = expandedFeatures.has(feature.key);
                const isFullyEnabled = isFeatureFullyEnabled(feature.key);
                const isPartial = isFeaturePartiallyEnabled(feature.key);
                const enabledCount = feature.permissions.filter(
                  (p) => permissions[feature.key]?.[p.key]
                ).length;

                return (
                  <div
                    key={feature.key}
                    className="border border-[#222222] rounded-lg overflow-hidden"
                  >
                    <div className="flex items-center gap-3 p-3 bg-[#0d0d0d]">
                      <button
                        type="button"
                        onClick={() => toggleAllForFeature(feature.key)}
                        className={`w-5 h-5 rounded border-2 flex items-center justify-center flex-shrink-0 transition-colors ${
                          isFullyEnabled
                            ? "bg-blue-600 border-blue-600"
                            : isPartial
                            ? "bg-blue-600/30 border-blue-600"
                            : "border-gray-600 hover:border-gray-400"
                        }`}
                      >
                        {isFullyEnabled && (
                          <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                          </svg>
                        )}
                        {isPartial && !isFullyEnabled && (
                          <div className="w-2 h-0.5 bg-blue-400 rounded" />
                        )}
                      </button>

                      <button
                        type="button"
                        onClick={() => toggleFeature(feature.key)}
                        className="flex-1 flex items-center justify-between text-left"
                      >
                        <div>
                          <span className="text-sm font-medium text-white">{feature.label}</span>
                          <span className="text-xs text-gray-500 ml-2">{feature.description}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-gray-500">
                            {enabledCount}/{feature.permissions.length}
                          </span>
                          {isExpanded ? (
                            <ChevronDown className="w-3.5 h-3.5 text-gray-500" />
                          ) : (
                            <ChevronRight className="w-3.5 h-3.5 text-gray-500" />
                          )}
                        </div>
                      </button>
                    </div>

                    {isExpanded && (
                      <div className="border-t border-[#222222]">
                        {feature.permissions.map((perm, idx) => (
                          <div
                            key={perm.key}
                            className={`flex items-center gap-3 px-4 py-2.5 ${
                              idx < feature.permissions.length - 1
                                ? "border-b border-[#1a1a1a]"
                                : ""
                            }`}
                          >
                            <button
                              type="button"
                              onClick={() => togglePermission(feature.key, perm.key)}
                              className={`w-4 h-4 rounded border-2 flex items-center justify-center flex-shrink-0 transition-colors ${
                                permissions[feature.key]?.[perm.key]
                                  ? "bg-blue-600 border-blue-600"
                                  : "border-gray-600 hover:border-gray-400"
                              }`}
                            >
                              {permissions[feature.key]?.[perm.key] && (
                                <svg className="w-2.5 h-2.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                                </svg>
                              )}
                            </button>
                            <span className="text-sm text-gray-300">{perm.label}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        <div className="flex gap-3 p-6 border-t border-[#222222] flex-shrink-0">
          <button
            onClick={onClose}
            className="flex-1 px-4 py-2.5 bg-[#1a1a1a] hover:bg-[#222222] text-gray-300 rounded-lg font-medium text-sm transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={loading || !name.trim()}
            className="flex-1 px-4 py-2.5 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-600/40 disabled:cursor-not-allowed text-white rounded-lg font-medium text-sm transition-colors flex items-center justify-center"
          >
            {loading ? (
              <div className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full" />
            ) : isEditing ? (
              "Save Changes"
            ) : (
              "Create Role"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
