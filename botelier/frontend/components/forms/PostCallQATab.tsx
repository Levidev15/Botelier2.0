"use client";

import { useState, useEffect } from "react";
import { Plus, Edit2, Trash2, GripVertical, Settings, ClipboardCheck, BarChart3, FileText } from "lucide-react";
import { notify, confirmAction } from "@/lib/notifications";
import { useAuthToken } from "@/lib/auth/useAuthToken";
import DispositionsTab from "@/components/forms/DispositionsTab";

interface AcwConfig {
  auto_run?: boolean;
  quality_rubric?: string;
  summary_enabled?: boolean;
  summary_prompt?: string;
  llm_model?: string;
}

interface ResolutionOption {
  id: string;
  assistant_id: string;
  name: string;
  description: string | null;
  display_order: number;
  is_active: boolean;
}

interface PostCallQATabProps {
  assistantId: string;
  accountId: string;
}

const DEFAULT_SUMMARY_PROMPT =
  "Provide a concise 2-3 sentence summary of the call. Include: the caller's primary intent, key actions taken by the assistant, and the final outcome. Focus on what matters for operational follow-up.";

const DEFAULT_QUALITY_RUBRIC =
  "Score 0-100 based on:\n- Accuracy of information provided (40%)\n- Empathy, professionalism, and tone (30%)\n- Efficiency and resolution speed (30%)";

export default function PostCallQATab({ assistantId, accountId }: PostCallQATabProps) {
  const { authFetch } = useAuthToken();
  const [acwConfig, setAcwConfig] = useState<AcwConfig>({});
  const [configLoading, setConfigLoading] = useState(true);

  const [resolutionOptions, setResolutionOptions] = useState<ResolutionOption[]>([]);
  const [resLoading, setResLoading] = useState(true);
  const [resShowForm, setResShowForm] = useState(false);
  const [resEditingId, setResEditingId] = useState<string | null>(null);
  const [resFormData, setResFormData] = useState({ name: "", description: "", is_active: true });

  const [qualityRubric, setQualityRubric] = useState("");
  const [qualitySaving, setQualitySaving] = useState(false);

  const [summaryPrompt, setSummaryPrompt] = useState("");
  const [summarySaving, setSummarySaving] = useState(false);
  const [llmModel, setLlmModel] = useState("");

  const LLM_MODELS = [
    { value: "gpt-4.1-nano", label: "GPT-4.1 Nano (cheapest)" },
    { value: "gpt-4.1-mini", label: "GPT-4.1 Mini (lightweight)" },
    { value: "gpt-4o-mini", label: "GPT-4o Mini (fast, cost-effective)" },
    { value: "gpt-4.1", label: "GPT-4.1 (standard)" },
    { value: "gpt-4o", label: "GPT-4o (higher quality)" },
  ];

  useEffect(() => {
    fetchAcwConfig();
    fetchResolutionOptions();
  }, [assistantId, accountId]);

  const fetchAcwConfig = async () => {
    try {
      const response = await authFetch(
        `/api/assistants/${assistantId}/acw-config?hotel_id=${accountId}`
      );
      if (response.ok) {
        const data = await response.json();
        setAcwConfig(data);
        setQualityRubric(data.quality_rubric || "");
        setSummaryPrompt(data.summary_prompt || "");
        setLlmModel(data.llm_model || "gpt-4o-mini");
      }
    } catch (error) {
      console.error("Error fetching ACW config:", error);
    } finally {
      setConfigLoading(false);
    }
  };

  const patchAcwConfig = async (updates: Partial<AcwConfig>) => {
    try {
      const response = await authFetch(
        `/api/assistants/${assistantId}/acw-config?hotel_id=${accountId}`,
        {
          method: "PATCH",
          body: JSON.stringify(updates),
        }
      );
      if (response.ok) {
        const data = await response.json();
        setAcwConfig(data);
        return true;
      }
      notify.error("Failed to save settings");
      return false;
    } catch (error) {
      notify.error("Error saving settings");
      return false;
    }
  };

  const fetchResolutionOptions = async () => {
    try {
      const response = await authFetch(
        `/api/assistants/${assistantId}/resolution-options?hotel_id=${accountId}`
      );
      if (response.ok) {
        const data = await response.json();
        setResolutionOptions(data);
      }
    } catch (error) {
      console.error("Error fetching resolution options:", error);
    } finally {
      setResLoading(false);
    }
  };

  const handleResSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const url = resEditingId
        ? `/api/assistants/${assistantId}/resolution-options/${resEditingId}?hotel_id=${accountId}`
        : `/api/assistants/${assistantId}/resolution-options?hotel_id=${accountId}`;
      const response = await authFetch(url, {
        method: resEditingId ? "PATCH" : "POST",
        body: JSON.stringify(resFormData),
      });
      if (response.ok) {
        notify.success(resEditingId ? "Resolution option updated" : "Resolution option created");
        fetchResolutionOptions();
        resetResForm();
      } else {
        notify.error("Failed to save resolution option");
      }
    } catch (error) {
      notify.error("Error saving resolution option");
    }
  };

  const handleResDelete = async (id: string) => {
    const confirmed = await confirmAction("Are you sure you want to delete this resolution option?", {
      confirmText: "Delete",
    });
    if (!confirmed) return;
    try {
      const response = await authFetch(
        `/api/assistants/${assistantId}/resolution-options/${id}?hotel_id=${accountId}`,
        { method: "DELETE" }
      );
      if (response.ok) {
        notify.success("Resolution option deleted");
        fetchResolutionOptions();
      } else {
        notify.error("Failed to delete resolution option");
      }
    } catch (error) {
      notify.error("Error deleting resolution option");
    }
  };

  const handleResEdit = (option: ResolutionOption) => {
    setResEditingId(option.id);
    setResFormData({
      name: option.name,
      description: option.description || "",
      is_active: option.is_active,
    });
    setResShowForm(true);
  };

  const resetResForm = () => {
    setResShowForm(false);
    setResEditingId(null);
    setResFormData({ name: "", description: "", is_active: true });
  };

  const saveQualityRubric = async () => {
    setQualitySaving(true);
    const ok = await patchAcwConfig({ quality_rubric: qualityRubric });
    if (ok) notify.success("Quality rubric saved");
    setQualitySaving(false);
  };

  const saveSummaryPrompt = async () => {
    setSummarySaving(true);
    const ok = await patchAcwConfig({ summary_prompt: summaryPrompt });
    if (ok) notify.success("Summary prompt saved");
    setSummarySaving(false);
  };

  if (configLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-indigo-500"></div>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Section 1: Settings */}
      <div className="bg-gray-800/50 rounded-lg border border-gray-700 p-5">
        <div className="flex items-center gap-3 mb-4">
          <Settings className="h-5 w-5 text-indigo-400" />
          <h3 className="text-lg font-medium text-white">Settings</h3>
        </div>
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-white">Auto-run after call</p>
              <p className="text-xs text-gray-400 mt-0.5">
                When enabled, Post Call QA runs automatically after every call. When disabled, use the AI button in call logs to run it manually.
              </p>
            </div>
            <button
              onClick={async () => {
                const newValue = !acwConfig.auto_run;
                const ok = await patchAcwConfig({ auto_run: newValue });
                if (ok) notify.success(newValue ? "Auto-run enabled" : "Auto-run disabled");
              }}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                acwConfig.auto_run ? "bg-indigo-600" : "bg-gray-600"
              }`}
            >
              <span
                className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                  acwConfig.auto_run ? "translate-x-6" : "translate-x-1"
                }`}
              />
            </button>
          </div>

          <div className="border-t border-gray-700 pt-4">
            <label className="block text-sm font-medium text-gray-300 mb-2">LLM Model</label>
            <select
              value={llmModel}
              onChange={async (e) => {
                const newModel = e.target.value;
                setLlmModel(newModel);
                const ok = await patchAcwConfig({ llm_model: newModel });
                if (ok) notify.success(`Model set to ${newModel}`);
              }}
              className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              {LLM_MODELS.map((model) => (
                <option key={model.value} value={model.value}>
                  {model.label}
                </option>
              ))}
            </select>
            <p className="text-xs text-gray-400 mt-1">
              Choose which OpenAI model to use for Post Call QA analysis
            </p>
          </div>
        </div>
      </div>

      {/* Section 2: Dispositions */}
      <div className="bg-gray-800/50 rounded-lg border border-gray-700 p-5">
        <div className="flex items-center gap-3 mb-4">
          <ClipboardCheck className="h-5 w-5 text-indigo-400" />
          <div>
            <h3 className="text-lg font-medium text-white">Dispositions</h3>
            <p className="text-xs text-gray-400">
              Define call outcomes the AI will choose from after each call
            </p>
          </div>
        </div>
        <DispositionsTab assistantId={assistantId} accountId={accountId} />
      </div>

      {/* Section 3: Resolution Status */}
      <div className="bg-gray-800/50 rounded-lg border border-gray-700 p-5">
        <div className="flex items-center gap-3 mb-4">
          <BarChart3 className="h-5 w-5 text-indigo-400" />
          <div>
            <h3 className="text-lg font-medium text-white">Resolution Status</h3>
            <p className="text-xs text-gray-400">
              Define resolution outcomes — the AI picks the best match based on the conversation
            </p>
          </div>
        </div>
        <div className="space-y-4">
          <div className="flex justify-end">
            {!resShowForm && (
              <button
                onClick={() => setResShowForm(true)}
                className="flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors text-sm"
              >
                <Plus className="h-4 w-4" />
                Add Option
              </button>
            )}
          </div>

          {resShowForm && (
            <form onSubmit={handleResSubmit} className="bg-gray-900 rounded-lg p-4 border border-gray-700 space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1">Name</label>
                <input
                  type="text"
                  value={resFormData.name}
                  onChange={(e) => setResFormData({ ...resFormData, name: e.target.value })}
                  placeholder="e.g., Fully Resolved"
                  className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1">
                  Description <span className="text-gray-500">(helps AI understand when to select this)</span>
                </label>
                <textarea
                  value={resFormData.description}
                  onChange={(e) => setResFormData({ ...resFormData, description: e.target.value })}
                  placeholder="e.g., The caller's issue was completely resolved during the call"
                  rows={2}
                  className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"
                />
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="res_is_active"
                  checked={resFormData.is_active}
                  onChange={(e) => setResFormData({ ...resFormData, is_active: e.target.checked })}
                  className="w-4 h-4 rounded border-gray-600 bg-gray-900 text-indigo-600 focus:ring-indigo-500"
                />
                <label htmlFor="res_is_active" className="text-sm text-gray-300">Active</label>
              </div>
              <div className="flex justify-end gap-2">
                <button type="button" onClick={resetResForm} className="px-4 py-2 text-gray-400 hover:text-white transition-colors">
                  Cancel
                </button>
                <button type="submit" className="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors">
                  {resEditingId ? "Update" : "Create"}
                </button>
              </div>
            </form>
          )}

          {resLoading ? (
            <div className="flex items-center justify-center py-8">
              <div className="animate-spin rounded-full h-6 w-6 border-t-2 border-b-2 border-indigo-500"></div>
            </div>
          ) : resolutionOptions.length === 0 && !resShowForm ? (
            <div className="text-center py-8 bg-gray-900/50 rounded-lg border border-gray-700 border-dashed">
              <p className="text-gray-400">No resolution options configured yet</p>
              <p className="text-sm text-gray-500 mt-1">
                Add options like "Fully Resolved", "Partially Resolved", "Unresolved"
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {resolutionOptions.map((option) => (
                <div
                  key={option.id}
                  className={`flex items-center gap-3 p-3 bg-gray-900 rounded-lg border border-gray-700 group ${
                    !option.is_active ? "opacity-50" : ""
                  }`}
                >
                  <GripVertical className="h-4 w-4 text-gray-600" />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-white font-medium">{option.name}</span>
                      {!option.is_active && (
                        <span className="text-xs text-gray-500 bg-gray-700 px-2 py-0.5 rounded">Inactive</span>
                      )}
                    </div>
                    {option.description && (
                      <p className="text-sm text-gray-400 truncate">{option.description}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button
                      onClick={() => handleResEdit(option)}
                      className="p-2 text-gray-400 hover:text-white hover:bg-gray-700 rounded-lg transition-colors"
                    >
                      <Edit2 className="h-4 w-4" />
                    </button>
                    <button
                      onClick={() => handleResDelete(option.id)}
                      className="p-2 text-gray-400 hover:text-red-400 hover:bg-gray-700 rounded-lg transition-colors"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Section 4: AI Quality Score */}
      <div className="bg-gray-800/50 rounded-lg border border-gray-700 p-5">
        <div className="flex items-center gap-3 mb-4">
          <BarChart3 className="h-5 w-5 text-indigo-400" />
          <div>
            <h3 className="text-lg font-medium text-white">AI Quality Score</h3>
            <p className="text-xs text-gray-400">
              Define the rubric the AI uses to score each call from 0 to 100
            </p>
          </div>
        </div>
        <div className="space-y-3">
          <textarea
            value={qualityRubric}
            onChange={(e) => setQualityRubric(e.target.value)}
            placeholder={DEFAULT_QUALITY_RUBRIC}
            rows={4}
            className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none text-sm"
          />
          <div className="flex items-center justify-between">
            <button
              type="button"
              onClick={() => setQualityRubric(DEFAULT_QUALITY_RUBRIC)}
              className="text-xs text-indigo-400 hover:text-indigo-300 transition-colors"
            >
              Use Botelier recommended rubric
            </button>
            <button
              onClick={saveQualityRubric}
              disabled={qualitySaving}
              className="px-4 py-1.5 bg-indigo-600 text-white text-sm rounded-lg hover:bg-indigo-700 transition-colors disabled:opacity-50"
            >
              {qualitySaving ? "Saving..." : "Save"}
            </button>
          </div>
        </div>
      </div>

      {/* Section 5: Call Summary */}
      <div className="bg-gray-800/50 rounded-lg border border-gray-700 p-5">
        <div className="flex items-center gap-3 mb-4">
          <FileText className="h-5 w-5 text-indigo-400" />
          <div className="flex-1">
            <h3 className="text-lg font-medium text-white">Call Summary</h3>
            <p className="text-xs text-gray-400">
              Generate an AI-written summary of each call
            </p>
          </div>
          <button
            onClick={async () => {
              const newValue = !acwConfig.summary_enabled;
              const ok = await patchAcwConfig({ summary_enabled: newValue });
              if (ok) notify.success(newValue ? "Summary generation enabled" : "Summary generation disabled");
            }}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
              acwConfig.summary_enabled ? "bg-indigo-600" : "bg-gray-600"
            }`}
          >
            <span
              className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                acwConfig.summary_enabled ? "translate-x-6" : "translate-x-1"
              }`}
            />
          </button>
        </div>

        {acwConfig.summary_enabled && (
          <div className="space-y-3">
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">Summary Prompt</label>
              <textarea
                value={summaryPrompt}
                onChange={(e) => setSummaryPrompt(e.target.value)}
                placeholder={DEFAULT_SUMMARY_PROMPT}
                rows={3}
                className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none text-sm"
              />
            </div>
            <div className="flex items-center justify-between">
              <button
                type="button"
                onClick={() => setSummaryPrompt(DEFAULT_SUMMARY_PROMPT)}
                className="text-xs text-indigo-400 hover:text-indigo-300 transition-colors"
              >
                Use Botelier recommended prompt
              </button>
              <button
                onClick={saveSummaryPrompt}
                disabled={summarySaving}
                className="px-4 py-1.5 bg-indigo-600 text-white text-sm rounded-lg hover:bg-indigo-700 transition-colors disabled:opacity-50"
              >
                {summarySaving ? "Saving..." : "Save"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
