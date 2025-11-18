"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, Info, Mic, MessageSquare, Volume2 } from "lucide-react";
import Link from "next/link";
import TabNavigation, { Tab } from "@/components/tabs/TabNavigation";
import FormSection from "@/components/forms/FormSection";
import FormField from "@/components/forms/FormField";
import ProviderSelector from "@/components/forms/ProviderSelector";
import SaveBar from "@/components/ui/SaveBar";

interface Assistant {
  id: string;
  hotel_id: string;
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
  system_prompt: string | null;
  first_message: string | null;
  language: string;
  temperature: number | null;
  max_tokens: number | null;
  is_active: boolean;
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
];

const DEMO_HOTEL_ID = "6b410bcc-f843-40df-b32d-078d3e01ac7f";

export default function AssistantConfigForm({ mode, assistantId }: AssistantConfigFormProps) {
  const router = useRouter();
  const scrollContainerRef = useRef<HTMLElement | null>(null);
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
    system_prompt: "You are a helpful hotel concierge assistant. Be friendly, professional, and helpful.",
    first_message: "Hello! Thank you for calling. How may I assist you today?",
    language: "en",
    temperature: 0.7,
    max_tokens: 150,
  });
  
  const [providers, setProviders] = useState<ProviderConfig>({ stt: {}, llm: {}, tts: {} });

  useEffect(() => {
    loadData();
  }, [mode, assistantId]);

  const loadData = async () => {
    if (mode === "edit" && assistantId) {
      await Promise.all([fetchAssistant(), fetchProviders()]);
    } else {
      await fetchProviders();
    }
    setLoading(false);
  };

  useEffect(() => {
    if (loading) return;
    
    scrollContainerRef.current = document.querySelector('main');
    
    const observers: IntersectionObserver[] = [];
    const intersectingEntries = new Map<string, IntersectionObserverEntry>();
    
    const observerCallback = (entries: IntersectionObserverEntry[]) => {
      entries.forEach((entry) => {
        const sectionId = entry.target.id.replace('section-', '');
        
        if (entry.isIntersecting) {
          intersectingEntries.set(sectionId, entry);
        } else {
          intersectingEntries.delete(sectionId);
        }
      });
      
      if (intersectingEntries.size > 0) {
        let closestSection = '';
        let closestDistance = Infinity;
        
        intersectingEntries.forEach((entry, sectionId) => {
          const distance = Math.abs(entry.boundingClientRect.top);
          if (distance < closestDistance) {
            closestDistance = distance;
            closestSection = sectionId;
          }
        });
        
        if (closestSection) {
          setActiveTab(closestSection);
        }
      }
    };

    const observerOptions = {
      root: scrollContainerRef.current,
      rootMargin: '-100px 0px -50% 0px',
      threshold: [0, 0.25, 0.5, 0.75, 1],
    };

    TABS.forEach(tab => {
      const element = document.getElementById(`section-${tab.id}`);
      if (element) {
        const observer = new IntersectionObserver(observerCallback, observerOptions);
        observer.observe(element);
        observers.push(observer);
      }
    });

    return () => {
      observers.forEach(observer => observer.disconnect());
    };
  }, [loading]);

  const fetchAssistant = async () => {
    if (!assistantId) return;
    
    try {
      const response = await fetch(`/api/assistants/${assistantId}`);
      if (!response.ok) throw new Error("Failed to fetch assistant");
      const data = await response.json();
      setAssistant(data);
      setFormData(data);
    } catch (error) {
      console.error("Failed to fetch assistant:", error);
      setAssistant(null);
    }
  };

  const fetchProviders = async () => {
    try {
      const [sttRes, llmRes, ttsRes] = await Promise.all([
        fetch('/api/providers/stt'),
        fetch('/api/providers/llm'),
        fetch('/api/providers/tts'),
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
        const response = await fetch("/api/assistants", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            ...formData,
            hotel_id: DEMO_HOTEL_ID,
            is_active: true,
          }),
        });

        if (!response.ok) throw new Error("Failed to create assistant");

        const data = await response.json();
        setIsDirty(false);
        router.push(`/dashboard/assistants/${data.id}`);
      } else {
        const response = await fetch(`/api/assistants/${assistantId}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
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
      alert(`Failed to ${mode === "create" ? "create" : "save"} assistant`);
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

  const scrollToSection = (tabId: string) => {
    setActiveTab(tabId);
    const element = document.getElementById(`section-${tabId}`);
    const container = scrollContainerRef.current;
    if (element && container) {
      const offset = 150;
      const elementPosition = element.getBoundingClientRect().top;
      const containerPosition = container.getBoundingClientRect().top;
      const scrollOffset = elementPosition - containerPosition + container.scrollTop - offset;
      container.scrollTo({
        top: scrollOffset,
        behavior: "smooth",
      });
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
    <div className="h-full pb-32">
      {/* Header */}
      <div className="border-b border-gray-800 bg-[#0a0a0a] sticky top-0 z-30">
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

      {/* Tab Navigation */}
      <div className="sticky top-[89px] z-20">
        <TabNavigation
          tabs={TABS}
          activeTab={activeTab}
          onTabChange={scrollToSection}
          sticky={false}
        />
      </div>

      {/* Content */}
      <div className="px-8 py-8 space-y-12">
        {/* Info Section */}
        <FormSection
          id="section-info"
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
        </FormSection>

        {/* Language Model Section */}
        <FormSection
          id="section-model"
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
            <input
              type="range"
              min="0"
              max="2"
              step="0.1"
              value={parseFloat(formData.temperature?.toString() || "0.7")}
              onChange={(e) => handleFieldChange("temperature", parseFloat(e.target.value))}
              className="w-full"
            />
            <div className="flex justify-between text-xs text-gray-500 mt-1">
              <span>Focused (0)</span>
              <span>Balanced (1)</span>
              <span>Creative (2)</span>
            </div>
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

        {/* Voice Section */}
        <FormSection
          id="section-voice"
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

        {/* Transcriber Section */}
        <FormSection
          id="section-transcriber"
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
