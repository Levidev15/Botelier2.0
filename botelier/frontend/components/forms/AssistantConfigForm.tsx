"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, Info, Mic, MessageSquare, Volume2, Activity, ClipboardCheck, Smartphone, PhoneCall } from "lucide-react";
import Link from "next/link";
import TabNavigation, { Tab } from "@/components/tabs/TabNavigation";
import FormSection from "@/components/forms/FormSection";
import FormField from "@/components/forms/FormField";
import ProviderSelector from "@/components/forms/ProviderSelector";
import SaveBar from "@/components/ui/SaveBar";
import { notify } from "@/lib/notifications";
import { useAccountContext } from "@/lib/auth/useAccountContext";
import { useAuthToken } from "@/lib/auth/useAuthToken";
import PostCallQATab from "@/components/forms/PostCallQATab";
import { useAccountFeatures } from "@/hooks/useAccountFeatures";

interface Assistant {
  id: string;
  account_id: string;
  name: string;
  description: string | null;
  stt_provider: string;
  llm_provider: string;
  tts_provider: string;
  stt_model: string | null;
  llm_model: string | null;
  tts_model: string | null;
  tts_voice: string | null;
  stt_config: any;
  llm_config: any;
  tts_config: any;
  vad_enabled: boolean;
  vad_provider: string | null;
  vad_config: any;
  system_prompt: string | null;
  first_message: string | null;
  language: string;
  temperature: number | null;
  max_tokens: number | null;
  is_active: boolean;
  knowledge_base_id: string | null;
  tool_set_id: string | null;
  mcp_connection_id: string | null;
  mcp_enabled_tools: string[];
  sms_config: any;
  call_settings: any;
}

interface KnowledgeBase {
  id: string;
  name: string;
  description: string | null;
  entry_count: number;
}

interface ToolSet {
  id: string;
  name: string;
  description: string | null;
  tool_count: number;
}

interface MCPConnection {
  id: string;
  name: string;
  description: string | null;
  status: string;
  is_active: boolean;
  discovered_tools: Array<{ name: string; description: string }>;
}

interface ProviderConfig {
  stt: any;
  llm: any;
  tts: any;
}

interface AssistantConfigFormProps {
  mode: "create" | "edit";
  assistantId?: string;
}

const TABS: Tab[] = [
  { id: "info", label: "Info", icon: <Info className="h-4 w-4" /> },
  { id: "model", label: "Language Model", icon: <MessageSquare className="h-4 w-4" /> },
  { id: "voice", label: "Voice", icon: <Volume2 className="h-4 w-4" /> },
  { id: "transcriber", label: "Transcriber", icon: <Mic className="h-4 w-4" /> },
  { id: "vad", label: "Voice Activity Detection", icon: <Activity className="h-4 w-4" /> },
  { id: "post-call-qa", label: "Post Call QA", icon: <ClipboardCheck className="h-4 w-4" /> },
  { id: "call-settings", label: "Call Settings", icon: <PhoneCall className="h-4 w-4" /> },
  { id: "sms", label: "SMS", icon: <Smartphone className="h-4 w-4" /> },
];

export default function AssistantConfigForm({ mode, assistantId }: AssistantConfigFormProps) {
  const router = useRouter();
  const { accountId, loading: contextLoading } = useAccountContext();
  const { authFetch } = useAuthToken();
  const { isFeatureEnabled } = useAccountFeatures();
  const [activeTab, setActiveTab] = useState("info");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [isDirty, setIsDirty] = useState(mode === "create");
  
  const [assistant, setAssistant] = useState<Assistant | null>(null);
  const [formData, setFormData] = useState<Partial<Assistant>>({
    name: "",
    description: "",
    stt_provider: "deepgram",
    llm_provider: "openai",
    tts_provider: "cartesia",
    stt_model: "",
    llm_model: "",
    tts_model: "",
    tts_voice: "",
    stt_config: {},
    vad_enabled: false,
    vad_provider: null,
    vad_config: {},
    system_prompt: "You are a helpful hotel concierge assistant. Be friendly, professional, and helpful.",
    first_message: "Hello! Thank you for calling. How may I assist you today?",
    language: "en",
    temperature: 0.7,
    max_tokens: 150,
    mcp_connection_id: null,
    mcp_enabled_tools: [],
    call_settings: {},
  });
  
  const [providers, setProviders] = useState<ProviderConfig>({ stt: {}, llm: {}, tts: {} });
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [toolSets, setToolSets] = useState<ToolSet[]>([]);
  const [mcpConnections, setMcpConnections] = useState<MCPConnection[]>([]);
  const [selectedMcpTools, setSelectedMcpTools] = useState<string[]>([]);

  useEffect(() => {
    loadData();
  }, [mode, assistantId]);

  useEffect(() => {
    if (accountId) {
      fetchKnowledgeBases();
      fetchToolSets();
      fetchMcpConnections();
    }
  }, [accountId]);

  const loadData = async () => {
    if (mode === "edit" && assistantId) {
      await Promise.all([fetchAssistant(), fetchProviders()]);
    } else {
      await fetchProviders();
    }
    setLoading(false);
  };


  const fetchAssistant = async () => {
    if (!assistantId) return;
    
    try {
      const response = await authFetch(`/api/assistants/${assistantId}`);
      if (!response.ok) throw new Error("Failed to fetch assistant");
      const data = await response.json();
      setAssistant(data);
      setFormData(data);
      if (data.mcp_enabled_tools) {
        setSelectedMcpTools(data.mcp_enabled_tools);
      }
    } catch (error) {
      console.error("Failed to fetch assistant:", error);
      setAssistant(null);
    }
  };

  const fetchProviders = async () => {
    try {
      const [sttRes, llmRes, ttsRes] = await Promise.all([
        authFetch('/api/providers/stt'),
        authFetch('/api/providers/llm'),
        authFetch('/api/providers/tts'),
      ]);
      
      const [sttData, llmData, ttsData] = await Promise.all([
        sttRes.json(),
        llmRes.json(),
        ttsRes.json(),
      ]);
      
      const sttProviders = sttData.providers || {};
      const llmProviders = llmData.providers || {};
      const ttsProviders = ttsData.providers || {};
      
      setProviders({
        stt: sttProviders,
        llm: llmProviders,
        tts: ttsProviders,
      });

      if (mode === "create") {
        setFormData(prev => ({
          ...prev,
          stt_model: sttProviders.deepgram?.default_model || "",
          llm_model: llmProviders.openai?.default_model || "",
          tts_model: ttsProviders.cartesia?.default_model || "",
          tts_voice: ttsProviders.cartesia?.voices?.[0]?.value || "",
        }));
      }
    } catch (error) {
      console.error("Failed to fetch providers:", error);
    }
  };

  const fetchKnowledgeBases = async () => {
    if (!accountId) return;
    try {
      const res = await authFetch(`/api/knowledge-bases?account_id=${accountId}`);
      const data = await res.json();
      setKnowledgeBases(data.knowledge_bases || []);
    } catch (error) {
      console.error("Failed to fetch knowledge bases:", error);
    }
  };

  const fetchToolSets = async () => {
    if (!accountId) return;
    try {
      const res = await authFetch(`/api/tool-sets?account_id=${accountId}`);
      const data = await res.json();
      setToolSets(data.tool_sets || []);
    } catch (error) {
      console.error("Failed to fetch tool sets:", error);
    }
  };

  const fetchMcpConnections = async () => {
    if (!accountId) return;
    try {
      const res = await authFetch(`/api/mcp-connections?account_id=${accountId}&include_tools=true`);
      if (res.ok) {
        const data = await res.json();
        setMcpConnections(data.filter((mcp: MCPConnection) => mcp.is_active && mcp.status === "connected"));
      }
    } catch (error) {
      console.error("Failed to fetch MCP connections:", error);
    }
  };

  const handleFieldChange = (field: keyof Assistant, value: any) => {
    setFormData((prev) => {
      const updated = { ...prev, [field]: value };
      
      if (mode === "edit" && assistant) {
        const hasChanges = Object.keys(updated).some(key => {
          const k = key as keyof Assistant;
          return updated[k] !== assistant[k];
        });
        setIsDirty(hasChanges);
      } else {
        setIsDirty(true);
      }
      
      return updated;
    });
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      if (mode === "create") {
        const response = await authFetch("/api/assistants", {
          method: "POST",
          body: JSON.stringify({
            ...formData,
            account_id: accountId,
            is_active: true,
          }),
        });

        if (!response.ok) throw new Error("Failed to create assistant");

        const data = await response.json();
        setIsDirty(false);
        router.push(`/dashboard/assistants/${data.id}`);
      } else {
        const response = await authFetch(`/api/assistants/${assistantId}`, {
          method: "PUT",
          body: JSON.stringify(formData),
        });

        if (!response.ok) throw new Error("Failed to save");

        const updated = await response.json();
        setAssistant(updated);
        setFormData(updated);
        setIsDirty(false);
      }
    } catch (error) {
      console.error("Failed to save:", error);
      notify.error(`Failed to ${mode === "create" ? "create" : "save"} assistant`);
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    if (mode === "edit" && assistant) {
      setFormData(assistant);
      setIsDirty(false);
    } else {
      router.push("/dashboard/assistants");
    }
  };


  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-gray-400">
          {mode === "create" ? "Loading configuration..." : "Loading assistant..."}
        </div>
      </div>
    );
  }

  if (mode === "edit" && !assistant) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-gray-400">Assistant not found</div>
      </div>
    );
  }

  const pageTitle = mode === "create" ? "Create New Assistant" : assistant?.name || "Edit Assistant";

  return (
    <div className={`h-full ${isDirty || saving ? 'pb-24' : 'pb-12'}`}>
      {/* Sticky Header + Tabs Container */}
      <div className="sticky top-0 z-30 bg-[#0a0a0a]">
        {/* Header */}
        <div className="border-b border-gray-800">
          <div className="px-8 py-6">
            <div className="flex items-center space-x-4">
              <Link
                href="/dashboard/assistants"
                className="text-gray-400 hover:text-white transition"
              >
                <ArrowLeft className="h-5 w-5" />
              </Link>
              <div>
                <h1 className="text-2xl font-bold">{pageTitle}</h1>
                <p className="text-sm text-gray-400 mt-1">
                  Configure your voice assistant
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Tab Navigation - now inside sticky container */}
        <TabNavigation
          tabs={mode === "create" ? TABS.filter(t => t.id !== "post-call-qa") : TABS}
          activeTab={activeTab}
          onTabChange={setActiveTab}
          sticky={false}
        />
      </div>

      {/* Content */}
      <div className="px-8 py-8">
        {/* Info Section */}
        {activeTab === "info" && (
        <FormSection
          title="Basic Information"
          description="Configure the basic details of your assistant"
        >
          <FormField label="Assistant Name" required>
            <input
              type="text"
              value={formData.name || ""}
              onChange={(e) => handleFieldChange("name", e.target.value)}
              placeholder="e.g., Front Desk Concierge"
              className="w-full px-3 py-2 bg-[#141414] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
            />
          </FormField>

          <FormField label="Description">
            <textarea
              value={formData.description || ""}
              onChange={(e) => handleFieldChange("description", e.target.value)}
              placeholder="Brief description of this assistant's purpose"
              rows={3}
              className="w-full px-3 py-2 bg-[#141414] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm resize-none"
            />
          </FormField>

          <FormField
            label="First Message"
            description="The greeting your assistant will say when answering a call"
          >
            <textarea
              value={formData.first_message || ""}
              onChange={(e) => handleFieldChange("first_message", e.target.value)}
              placeholder="e.g., Hello! Thank you for calling. How may I assist you today?"
              rows={3}
              className="w-full px-3 py-2 bg-[#141414] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm resize-none"
            />
          </FormField>

          <FormField label="Language">
            <select
              value={formData.language || "en"}
              onChange={(e) => handleFieldChange("language", e.target.value)}
              className="w-full px-3 py-2 bg-[#141414] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
            >
              <option value="en">English</option>
              <option value="es">Spanish</option>
              <option value="fr">French</option>
              <option value="de">German</option>
            </select>
          </FormField>

          <FormField 
            label="Knowledge Base" 
            description="Assign a knowledge base for the assistant to reference during calls"
          >
            <select
              value={formData.knowledge_base_id || ""}
              onChange={(e) => handleFieldChange("knowledge_base_id", e.target.value || null)}
              className="w-full px-3 py-2 bg-[#141414] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
            >
              <option value="">No knowledge base</option>
              {knowledgeBases.map((kb) => (
                <option key={kb.id} value={kb.id}>
                  {kb.name} ({kb.entry_count} entries)
                </option>
              ))}
            </select>
          </FormField>

          <FormField 
            label="Tool Set" 
            description="Assign a set of tools (actions) the assistant can perform during calls"
          >
            <select
              value={formData.tool_set_id || ""}
              onChange={(e) => handleFieldChange("tool_set_id", e.target.value || null)}
              className="w-full px-3 py-2 bg-[#141414] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
            >
              <option value="">No tool set</option>
              {toolSets.map((ts) => (
                <option key={ts.id} value={ts.id}>
                  {ts.name} ({ts.tool_count} tools)
                </option>
              ))}
            </select>
          </FormField>

          <FormField 
            label="MCP Connection" 
            description="Connect to an external MCP server to provide additional dynamic tools"
          >
            <select
              value={formData.mcp_connection_id || ""}
              onChange={(e) => {
                const newId = e.target.value || null;
                handleFieldChange("mcp_connection_id", newId);
                if (!newId) {
                  handleFieldChange("mcp_enabled_tools", []);
                  setSelectedMcpTools([]);
                } else {
                  const mcp = mcpConnections.find(m => m.id === newId);
                  if (mcp) {
                    const allTools = mcp.discovered_tools.map(t => t.name);
                    handleFieldChange("mcp_enabled_tools", allTools);
                    setSelectedMcpTools(allTools);
                  }
                }
              }}
              className="w-full px-3 py-2 bg-[#141414] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
            >
              <option value="">No MCP connection</option>
              {mcpConnections.map((mcp) => (
                <option key={mcp.id} value={mcp.id}>
                  {mcp.name} ({mcp.discovered_tools?.length || 0} tools)
                </option>
              ))}
            </select>
          </FormField>

          {formData.mcp_connection_id && (() => {
            const mcp = mcpConnections.find(m => m.id === formData.mcp_connection_id);
            if (!mcp || !mcp.discovered_tools?.length) return null;
            return (
              <FormField 
                label="Enabled MCP Tools" 
                description="Select which tools from this MCP connection should be available to the assistant"
              >
                <div className="space-y-2 max-h-48 overflow-y-auto p-3 bg-[#0a0a0a] border border-gray-800 rounded-lg">
                  {mcp.discovered_tools.map((tool) => {
                    const isEnabled = (formData.mcp_enabled_tools || []).includes(tool.name);
                    return (
                      <label key={tool.name} className="flex items-start gap-3 cursor-pointer hover:bg-gray-800/50 p-2 rounded">
                        <input
                          type="checkbox"
                          checked={isEnabled}
                          onChange={(e) => {
                            const current = formData.mcp_enabled_tools || [];
                            const updated = e.target.checked
                              ? [...current, tool.name]
                              : current.filter((t: string) => t !== tool.name);
                            handleFieldChange("mcp_enabled_tools", updated);
                            setSelectedMcpTools(updated);
                          }}
                          className="mt-1 h-4 w-4 rounded border-gray-700 bg-[#141414] text-blue-600 focus:ring-blue-600"
                        />
                        <div>
                          <div className="text-sm font-medium">{tool.name}</div>
                          {tool.description && (
                            <div className="text-xs text-gray-500">{tool.description}</div>
                          )}
                        </div>
                      </label>
                    );
                  })}
                </div>
              </FormField>
            );
          })()}
        </FormSection>
        )}

        {/* Language Model Section */}
        {activeTab === "model" && (
        <FormSection
          title="Language Model Configuration"
          description="Configure the AI that powers conversations"
        >
          <ProviderSelector
            label="LLM Provider"
            description="Service that generates intelligent responses"
            providerValue={formData.llm_provider || ""}
            modelValue={formData.llm_model || ""}
            providers={Object.entries(providers.llm).map(([key, config]: [string, any]) => ({
              value: key,
              label: config.display_name || key,
            }))}
            models={formData.llm_provider && providers.llm[formData.llm_provider]?.models 
              ? providers.llm[formData.llm_provider].models.map((m: any) => ({
                  value: m.value,
                  label: m.label,
                }))
              : []}
            onProviderChange={(value) => {
              handleFieldChange("llm_provider", value);
              const defaultModel = providers.llm[value]?.default_model;
              if (defaultModel) {
                handleFieldChange("llm_model", defaultModel);
              }
            }}
            onModelChange={(value) => handleFieldChange("llm_model", value)}
          />

          <FormField
            label="System Prompt"
            description="Instructions that define the assistant's personality and behavior"
            required
          >
            <textarea
              value={formData.system_prompt || ""}
              onChange={(e) => handleFieldChange("system_prompt", e.target.value)}
              placeholder="You are a helpful hotel concierge assistant..."
              rows={12}
              className="w-full px-3 py-2 bg-[#141414] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm resize-none font-mono"
            />
          </FormField>

          <FormField
            label="Temperature"
            description={`Controls creativity (${formData.temperature || "0.7"}). Lower = more focused, Higher = more creative`}
          >
            {(() => {
              const maxTemp = formData.llm_provider === "anthropic" ? 1 : 2;
              return (
                <>
                  <input
                    type="range"
                    min="0"
                    max={maxTemp}
                    step="0.1"
                    value={Math.min(parseFloat(formData.temperature?.toString() || "0.7"), maxTemp)}
                    onChange={(e) => handleFieldChange("temperature", parseFloat(e.target.value))}
                    className="w-full"
                  />
                  <div className="flex justify-between text-xs text-gray-500 mt-1">
                    <span>Focused (0)</span>
                    <span>Balanced ({maxTemp === 1 ? "0.5" : "1"})</span>
                    <span>Creative ({maxTemp})</span>
                  </div>
                </>
              );
            })()}
          </FormField>

          <FormField
            label="Max Tokens"
            description="Maximum length of each response"
          >
            <input
              type="number"
              value={formData.max_tokens || 150}
              onChange={(e) => handleFieldChange("max_tokens", parseInt(e.target.value))}
              placeholder="150"
              className="w-full px-3 py-2 bg-[#141414] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
            />
          </FormField>
        </FormSection>
        )}

        {/* Voice Section */}
        {activeTab === "voice" && (
        <FormSection
          title="Text-to-Speech Configuration"
          description="Configure how responses are spoken"
        >
          <FormField label="TTS Provider" description="Service that converts text into natural-sounding voice" required>
            <select
              value={formData.tts_provider || ""}
              onChange={(e) => {
                const newProvider = e.target.value;
                handleFieldChange("tts_provider", newProvider);
                const defaultModel = providers.tts[newProvider]?.default_model;
                if (defaultModel) {
                  handleFieldChange("tts_model", defaultModel);
                }
                if (newProvider === "deepgram" && defaultModel) {
                  const voicesByModel = providers.tts[newProvider]?.voices_by_model?.[defaultModel];
                  if (voicesByModel?.[0]?.value) {
                    handleFieldChange("tts_voice", voicesByModel[0].value);
                  }
                } else {
                  const defaultVoice = providers.tts[newProvider]?.voices?.[0]?.value;
                  if (defaultVoice) {
                    handleFieldChange("tts_voice", defaultVoice);
                  }
                }
              }}
              className="w-full px-3 py-2 bg-[#141414] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
            >
              <option value="">Select provider...</option>
              {Object.entries(providers.tts).map(([key, config]: [string, any]) => (
                <option key={key} value={key}>
                  {config.display_name || key}
                </option>
              ))}
            </select>
          </FormField>

          {formData.tts_provider && providers.tts[formData.tts_provider]?.models && (
            <FormField label="TTS Model" description="The specific model to use for speech synthesis" required>
              <select
                value={formData.tts_model || ""}
                onChange={(e) => {
                  const newModel = e.target.value;
                  handleFieldChange("tts_model", newModel);
                  if (formData.tts_provider === "deepgram") {
                    const voicesByModel = providers.tts[formData.tts_provider]?.voices_by_model?.[newModel];
                    if (voicesByModel?.[0]?.value) {
                      handleFieldChange("tts_voice", voicesByModel[0].value);
                    }
                  }
                }}
                className="w-full px-3 py-2 bg-[#141414] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
              >
                <option value="">Select model...</option>
                {providers.tts[formData.tts_provider].models.map((model: any) => (
                  <option key={model.value} value={model.value}>
                    {model.label}
                  </option>
                ))}
              </select>
            </FormField>
          )}

          {formData.tts_provider && formData.tts_model && (() => {
            const ttsConfig = providers.tts[formData.tts_provider];
            let voiceOptions: any[] = [];
            
            if (formData.tts_provider === "deepgram" && ttsConfig?.voices_by_model) {
              voiceOptions = ttsConfig.voices_by_model[formData.tts_model] || [];
            } else if (ttsConfig?.voices) {
              voiceOptions = ttsConfig.voices;
            }
            
            return voiceOptions.length > 0 ? (
              <FormField label="Voice" description="The voice to use for speech synthesis" required>
                <select
                  value={formData.tts_voice || ""}
                  onChange={(e) => handleFieldChange("tts_voice", e.target.value)}
                  className="w-full px-3 py-2 bg-[#141414] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
                >
                  <option value="">Select voice...</option>
                  {voiceOptions.map((voice: any) => (
                    <option key={voice.value} value={voice.value}>
                      {voice.label}
                    </option>
                  ))}
                </select>
              </FormField>
            ) : null;
          })()}
        </FormSection>
        )}

        {/* Transcriber Section */}
        {activeTab === "transcriber" && (
        <FormSection
          title="Speech-to-Text Configuration"
          description="Configure how voice is converted to text"
        >
          <ProviderSelector
            label="STT Provider"
            description="Service that converts speech to text"
            providerValue={formData.stt_provider || ""}
            modelValue={formData.stt_model || ""}
            providers={Object.entries(providers.stt).map(([key, config]: [string, any]) => ({
              value: key,
              label: config.display_name || key,
            }))}
            models={formData.stt_provider && providers.stt[formData.stt_provider]?.models 
              ? providers.stt[formData.stt_provider].models.map((m: any) => ({
                  value: m.value,
                  label: m.label,
                }))
              : []}
            onProviderChange={(value) => {
              handleFieldChange("stt_provider", value);
              const defaultModel = providers.stt[value]?.default_model;
              if (defaultModel) {
                handleFieldChange("stt_model", defaultModel);
              }
            }}
            onModelChange={(value) => handleFieldChange("stt_model", value)}
          />

          {formData.stt_provider === "deepgram" && 
           formData.stt_model && 
           formData.stt_model.includes("flux") && 
           providers.stt.deepgram?.flux_params && (
            <>
              <div className="border-t border-gray-700 pt-6 mt-6">
                <h3 className="text-sm font-semibold text-gray-200 mb-4">Deepgram Flux Parameters</h3>
                <div className="space-y-6">
                  <FormField
                    label="EOT Threshold"
                    description="End-of-Turn threshold (0.0-1.0). Controls when the model considers speech complete. Default: 0.7"
                  >
                    <input
                      type="number"
                      min="0"
                      max="1"
                      step="0.1"
                      value={formData.stt_config?.eot_threshold ?? 0.7}
                      onChange={(e) => {
                        const newConfig = { ...formData.stt_config, eot_threshold: parseFloat(e.target.value) };
                        handleFieldChange("stt_config", newConfig);
                      }}
                      className="w-full px-3 py-2 bg-[#141414] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
                    />
                  </FormField>

                  <FormField
                    label="EOT Timeout (ms)"
                    description="End-of-Turn timeout in milliseconds (1000-10000). How long to wait before considering speech ended. Default: 5000"
                  >
                    <input
                      type="number"
                      min="1000"
                      max="10000"
                      step="500"
                      value={formData.stt_config?.eot_timeout_ms ?? 5000}
                      onChange={(e) => {
                        const newConfig = { ...formData.stt_config, eot_timeout_ms: parseInt(e.target.value) };
                        handleFieldChange("stt_config", newConfig);
                      }}
                      className="w-full px-3 py-2 bg-[#141414] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
                    />
                  </FormField>

                  <FormField
                    label="Eager EOT Threshold"
                    description="Eager End-of-Turn threshold (0.0-1.0). Optional. Enables faster turn detection for shorter utterances."
                  >
                    <input
                      type="number"
                      min="0"
                      max="1"
                      step="0.1"
                      value={formData.stt_config?.eager_eot_threshold ?? ""}
                      onChange={(e) => {
                        const value = e.target.value;
                        const newConfig = { ...formData.stt_config };
                        if (value === "") {
                          delete newConfig.eager_eot_threshold;
                        } else {
                          newConfig.eager_eot_threshold = parseFloat(value);
                        }
                        handleFieldChange("stt_config", newConfig);
                      }}
                      placeholder="Optional"
                      className="w-full px-3 py-2 bg-[#141414] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
                    />
                  </FormField>
                </div>
              </div>
            </>
          )}
        </FormSection>
        )}

        {/* VAD Section */}
        {activeTab === "vad" && (
        <FormSection
          title="Voice Activity Detection (VAD)"
          description="Optional: Detect when users start and stop speaking"
        >
          <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-4 mb-6">
            <div className="flex items-start space-x-3">
              <Info className="h-5 w-5 text-blue-400 mt-0.5 flex-shrink-0" />
              <div className="text-sm text-blue-200">
                <p className="font-semibold mb-1">Important Note</p>
                <p>
                  Do not enable external VAD if you&apos;re using a speech-to-text provider with built-in voice activity detection (like Deepgram Flux). 
                  Built-in VAD is often more accurate because it uses both acoustic and textual cues. External VAD is useful for interruption 
                  detection or when using STT providers without built-in VAD.
                </p>
              </div>
            </div>
          </div>

          <FormField
            label="Enable VAD"
            description="Turn on voice activity detection for this assistant"
          >
            <label className="flex items-center space-x-3 cursor-pointer">
              <input
                type="checkbox"
                checked={formData.vad_enabled || false}
                onChange={(e) => handleFieldChange("vad_enabled", e.target.checked)}
                className="w-4 h-4 bg-[#141414] border border-gray-800 rounded focus:ring-2 focus:ring-blue-600"
              />
              <span className="text-sm text-gray-300">
                {formData.vad_enabled ? "VAD Enabled" : "VAD Disabled"}
              </span>
            </label>
          </FormField>

          {formData.vad_enabled && (
            <>
              <FormField
                label="VAD Provider"
                description="Choose the voice activity detection algorithm"
                required
              >
                <select
                  value={formData.vad_provider || ""}
                  onChange={(e) => handleFieldChange("vad_provider", e.target.value)}
                  className="w-full px-3 py-2 bg-[#141414] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
                >
                  <option value="">Select VAD provider...</option>
                  <option value="silero">Silero VAD (High accuracy ML-based)</option>
                  <option value="webrtc">WebRTC VAD (Built into Daily transport)</option>
                  <option value="aic">AIC VAD (Advanced interruption control)</option>
                </select>
              </FormField>

              <div className="border-t border-gray-700 pt-6 mt-6">
                <h3 className="text-sm font-semibold text-gray-200 mb-4">Advanced VAD Parameters</h3>
                <div className="space-y-6">
                  <FormField
                    label="Confidence Threshold"
                    description="Confidence level (0.0-1.0) to consider speech detected. Higher = more strict. Default: 0.5"
                  >
                    <input
                      type="number"
                      min="0"
                      max="1"
                      step="0.1"
                      value={formData.vad_config?.confidence ?? 0.5}
                      onChange={(e) => {
                        const newConfig = { ...formData.vad_config, confidence: parseFloat(e.target.value) };
                        handleFieldChange("vad_config", newConfig);
                      }}
                      className="w-full px-3 py-2 bg-[#141414] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
                    />
                  </FormField>

                  <FormField
                    label="Start Delay (seconds)"
                    description="How long voice must be detected before considering speech started. Default: 0.2"
                  >
                    <input
                      type="number"
                      min="0"
                      max="2"
                      step="0.1"
                      value={formData.vad_config?.start_secs ?? 0.2}
                      onChange={(e) => {
                        const newConfig = { ...formData.vad_config, start_secs: parseFloat(e.target.value) };
                        handleFieldChange("vad_config", newConfig);
                      }}
                      className="w-full px-3 py-2 bg-[#141414] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
                    />
                  </FormField>

                  <FormField
                    label="Stop Delay (seconds)"
                    description="How long silence must be detected before considering speech ended. Default: 0.8"
                  >
                    <input
                      type="number"
                      min="0"
                      max="5"
                      step="0.1"
                      value={formData.vad_config?.stop_secs ?? 0.8}
                      onChange={(e) => {
                        const newConfig = { ...formData.vad_config, stop_secs: parseFloat(e.target.value) };
                        handleFieldChange("vad_config", newConfig);
                      }}
                      className="w-full px-3 py-2 bg-[#141414] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
                    />
                  </FormField>

                  <FormField
                    label="Minimum Volume"
                    description="Minimum audio volume (0.0-1.0) to consider for VAD. Helps filter out background noise. Default: 0.6"
                  >
                    <input
                      type="number"
                      min="0"
                      max="1"
                      step="0.1"
                      value={formData.vad_config?.min_volume ?? 0.6}
                      onChange={(e) => {
                        const newConfig = { ...formData.vad_config, min_volume: parseFloat(e.target.value) };
                        handleFieldChange("vad_config", newConfig);
                      }}
                      className="w-full px-3 py-2 bg-[#141414] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
                    />
                  </FormField>
                </div>
              </div>
            </>
          )}
        </FormSection>
        )}

        {/* Post Call QA Section - Only show in edit mode */}
        {activeTab === "post-call-qa" && mode === "edit" && assistantId && accountId && (
        <FormSection
          title="Post Call QA"
          description="Configure automated post-call analysis: dispositions, resolution tracking, quality scoring, and AI summaries"
        >
          <PostCallQATab assistantId={assistantId} accountId={accountId} />
        </FormSection>
        )}

        {/* SMS Configuration Section */}
        {activeTab === "sms" && (
        <FormSection
          title="SMS Channel"
          description="Enable AI-powered SMS conversations using this assistant's knowledge base, system prompt, and tools"
        >
          <div className="space-y-6">
            <div className="flex items-center gap-3">
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={formData.sms_config?.enabled || false}
                  onChange={(e) => {
                    setFormData(prev => ({
                      ...prev,
                      sms_config: {
                        ...prev.sms_config,
                        enabled: e.target.checked,
                      }
                    }));
                    setIsDirty(true);
                  }}
                  className="sr-only peer"
                />
                <div className="w-11 h-6 bg-[#2a2a2a] peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-indigo-600"></div>
              </label>
              <div>
                <span className="text-sm font-medium text-white">Enable SMS</span>
                <p className="text-xs text-gray-400">Allow this assistant to respond to incoming text messages</p>
              </div>
            </div>

            {formData.sms_config?.enabled && (
              <>
                <FormField label="LLM Model Override" tooltip="Use a different model for SMS responses (leave empty to use the voice model)">
                  <input
                    type="text"
                    value={formData.sms_config?.llm_model || ""}
                    onChange={(e) => {
                      setFormData(prev => ({
                        ...prev,
                        sms_config: { ...prev.sms_config, llm_model: e.target.value || undefined }
                      }));
                      setIsDirty(true);
                    }}
                    placeholder={formData.llm_model || "Same as voice model"}
                    className="w-full px-3 py-2 bg-[#1a1a1a] border border-[#333] rounded-lg text-sm text-white placeholder-gray-500 focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500"
                  />
                </FormField>

                <FormField label="Max Response Length" tooltip="Maximum characters per SMS response (default: 480, roughly 3 SMS segments)">
                  <input
                    type="number"
                    value={formData.sms_config?.max_response_length || 480}
                    onChange={(e) => {
                      setFormData(prev => ({
                        ...prev,
                        sms_config: { ...prev.sms_config, max_response_length: parseInt(e.target.value) || 480 }
                      }));
                      setIsDirty(true);
                    }}
                    min={100}
                    max={1600}
                    className="w-full px-3 py-2 bg-[#1a1a1a] border border-[#333] rounded-lg text-sm text-white focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500"
                  />
                </FormField>

                <FormField label="Session Timeout (hours)" tooltip="How long before an inactive conversation is considered a new session (default: 24 hours)">
                  <input
                    type="number"
                    value={formData.sms_config?.session_timeout_hours || 24}
                    onChange={(e) => {
                      setFormData(prev => ({
                        ...prev,
                        sms_config: { ...prev.sms_config, session_timeout_hours: parseInt(e.target.value) || 24 }
                      }));
                      setIsDirty(true);
                    }}
                    min={1}
                    max={168}
                    className="w-full px-3 py-2 bg-[#1a1a1a] border border-[#333] rounded-lg text-sm text-white focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500"
                  />
                </FormField>

                <FormField label="Welcome Message" tooltip="Optional message sent when a new conversation starts (leave empty for no welcome message)">
                  <textarea
                    value={formData.sms_config?.welcome_message || ""}
                    onChange={(e) => {
                      setFormData(prev => ({
                        ...prev,
                        sms_config: { ...prev.sms_config, welcome_message: e.target.value || undefined }
                      }));
                      setIsDirty(true);
                    }}
                    placeholder="e.g., Hi! How can I help you today?"
                    rows={2}
                    className="w-full px-3 py-2 bg-[#1a1a1a] border border-[#333] rounded-lg text-sm text-white placeholder-gray-500 focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500 resize-none"
                  />
                </FormField>

                <FormField label="SMS-Specific Instructions" tooltip="Additional instructions for the AI when responding via SMS (added to the system prompt)">
                  <textarea
                    value={formData.sms_config?.prompt_additions || ""}
                    onChange={(e) => {
                      setFormData(prev => ({
                        ...prev,
                        sms_config: { ...prev.sms_config, prompt_additions: e.target.value || undefined }
                      }));
                      setIsDirty(true);
                    }}
                    placeholder="e.g., Always include booking links when discussing reservations. Respond in Spanish if the customer writes in Spanish."
                    rows={3}
                    className="w-full px-3 py-2 bg-[#1a1a1a] border border-[#333] rounded-lg text-sm text-white placeholder-gray-500 focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500 resize-none"
                  />
                </FormField>

                <FormField label="History Messages" tooltip="Number of previous messages to include as context (default: 20)">
                  <input
                    type="number"
                    value={formData.sms_config?.max_history_messages || 20}
                    onChange={(e) => {
                      setFormData(prev => ({
                        ...prev,
                        sms_config: { ...prev.sms_config, max_history_messages: parseInt(e.target.value) || 20 }
                      }));
                      setIsDirty(true);
                    }}
                    min={5}
                    max={50}
                    className="w-full px-3 py-2 bg-[#1a1a1a] border border-[#333] rounded-lg text-sm text-white focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500"
                  />
                </FormField>

                <div className="p-3 bg-[#1a1a1a] border border-[#333] rounded-lg">
                  <p className="text-xs text-gray-400">
                    <strong className="text-gray-300">How it works:</strong> SMS conversations use this assistant&apos;s system prompt, knowledge base, and tools. 
                    To activate, enable SMS here and then turn on SMS on a phone number in the Phone Numbers page.
                    Customers can text STOP to opt out and START to re-subscribe.
                  </p>
                </div>
              </>
            )}
          </div>
        </FormSection>
        )}

        {/* Call Settings Section */}
        {activeTab === "call-settings" && (
        <FormSection
          title="Call Settings"
          description="Configure per-assistant call control thresholds used for analytics and future call-lifecycle enforcement"
        >
          <div className="space-y-6">
            <FormField
              label="Max Call Duration (seconds)"
              tooltip="Reserved for future use: maximum allowed call length before automatic hang-up. Default: 600 seconds (10 min)."
            >
              <input
                type="number"
                value={formData.call_settings?.max_call_duration_seconds ?? 600}
                onChange={(e) => {
                  const val = parseInt(e.target.value, 10);
                  setFormData(prev => ({
                    ...prev,
                    call_settings: {
                      ...(prev.call_settings || {}),
                      max_call_duration_seconds: isNaN(val) ? 600 : val,
                    }
                  }));
                  setIsDirty(true);
                }}
                min={30}
                max={3600}
                className="w-full px-3 py-2 bg-[#1a1a1a] border border-[#333] rounded-lg text-sm text-white focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500"
              />
            </FormField>

            <FormField
              label="No-Response Timeout (seconds)"
              tooltip="Reserved for future use: seconds of silence before the assistant ends the call. Default: 10 seconds."
            >
              <input
                type="number"
                value={formData.call_settings?.no_response_timeout_seconds ?? 10}
                onChange={(e) => {
                  const val = parseInt(e.target.value, 10);
                  setFormData(prev => ({
                    ...prev,
                    call_settings: {
                      ...(prev.call_settings || {}),
                      no_response_timeout_seconds: isNaN(val) ? 10 : val,
                    }
                  }));
                  setIsDirty(true);
                }}
                min={5}
                max={120}
                className="w-full px-3 py-2 bg-[#1a1a1a] border border-[#333] rounded-lg text-sm text-white focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500"
              />
            </FormField>

            {isFeatureEnabled("call_recording") && (
              <FormField
                label="Call Recording"
                tooltip="Record inbound calls as dual-channel audio. Recordings are available in the call log once the call ends. Recordings stop automatically before any call transfer."
              >
                <label className="flex items-center gap-3 cursor-pointer">
                  <div className="relative">
                    <input
                      type="checkbox"
                      className="sr-only"
                      checked={!!(formData.call_settings?.call_recording_enabled)}
                      onChange={(e) => {
                        setFormData(prev => ({
                          ...prev,
                          call_settings: {
                            ...(prev.call_settings || {}),
                            call_recording_enabled: e.target.checked,
                          }
                        }));
                        setIsDirty(true);
                      }}
                    />
                    <div className={`w-10 h-5 rounded-full transition-colors ${formData.call_settings?.call_recording_enabled ? "bg-indigo-600" : "bg-gray-700"}`} />
                    <div className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${formData.call_settings?.call_recording_enabled ? "translate-x-5" : ""}`} />
                  </div>
                  <span className="text-sm text-gray-300">
                    {formData.call_settings?.call_recording_enabled ? "Recording enabled" : "Recording disabled"}
                  </span>
                </label>
              </FormField>
            )}

            <div className="p-3 bg-[#1a1a1a] border border-[#333] rounded-lg">
              <p className="text-xs text-gray-400">
                <strong className="text-gray-300">Dropped Before AI</strong> calls are now detected directly by the pipeline — a call is classified as dropped when the AI greeting never finished playing. Max Call Duration and No-Response Timeout are stored but not yet enforced by the pipeline.
              </p>
            </div>
          </div>
        </FormSection>
        )}
      </div>

      {/* Save Bar */}
      <SaveBar
        onSave={handleSave}
        onCancel={handleCancel}
        isSaving={saving}
        isDirty={isDirty}
      />
    </div>
  );
}
