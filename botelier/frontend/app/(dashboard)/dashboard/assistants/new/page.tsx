"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, Info, Mic, MessageSquare, Volume2 } from "lucide-react";
import Link from "next/link";
import TabNavigation, { Tab } from "@/components/tabs/TabNavigation";
import FormSection from "@/components/forms/FormSection";
import FormField from "@/components/forms/FormField";
import ProviderSelector from "@/components/forms/ProviderSelector";
import SaveBar from "@/components/ui/SaveBar";

interface FormData {
  name: string;
  description: string;
  stt_provider: string;
  llm_provider: string;
  tts_provider: string;
  stt_model: string;
  llm_model: string;
  tts_voice: string;
  system_prompt: string;
  first_message: string;
  language: string;
  temperature: number;
  max_tokens: number;
}

interface ProviderConfig {
  stt: any;
  llm: any;
  tts: any;
}

const TABS: Tab[] = [
  { id: "info", label: "Info", icon: <Info className="h-4 w-4" /> },
  { id: "model", label: "Language Model", icon: <MessageSquare className="h-4 w-4" /> },
  { id: "voice", label: "Voice", icon: <Volume2 className="h-4 w-4" /> },
  { id: "transcriber", label: "Transcriber", icon: <Mic className="h-4 w-4" /> },
];

const DEMO_HOTEL_ID = "6b410bcc-f843-40df-b32d-078d3e01ac7f";

export default function NewAssistantPage() {
  const router = useRouter();
  const [activeTab, setActiveTab] = useState("info");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [isDirty, setIsDirty] = useState(true); // Always enabled on create page
  
  const [formData, setFormData] = useState<FormData>({
    name: "",
    description: "",
    stt_provider: "deepgram",
    llm_provider: "openai",
    tts_provider: "cartesia",
    stt_model: "",
    llm_model: "",
    tts_voice: "",
    system_prompt: "You are a helpful hotel concierge assistant. Be friendly, professional, and helpful.",
    first_message: "Hello! Thank you for calling. How may I assist you today?",
    language: "en",
    temperature: 0.7,
    max_tokens: 150,
  });
  
  const [providers, setProviders] = useState<ProviderConfig>({ stt: {}, llm: {}, tts: {} });

  useEffect(() => {
    fetchProviders();
  }, []);

  useEffect(() => {
    if (loading) return; // Don't setup observers until data is loaded
    
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
        const topEntry = Array.from(intersectingEntries.values()).reduce((prev, curr) => {
          return prev.boundingClientRect.top < curr.boundingClientRect.top ? prev : curr;
        });
        
        const topSectionId = topEntry.target.id.replace('section-', '');
        setActiveTab(topSectionId);
      }
    };

    const observerOptions = {
      root: null,
      rootMargin: '-150px 0px -50% 0px',
      threshold: 0,
    };

    const sectionIds = ['info', 'model', 'voice', 'transcriber'];
    sectionIds.forEach((sectionId) => {
      const element = document.getElementById(`section-${sectionId}`);
      if (element) {
        const observer = new IntersectionObserver(observerCallback, observerOptions);
        observer.observe(element);
        observers.push(observer);
      }
    });

    return () => {
      observers.forEach((observer) => observer.disconnect());
    };
  }, [loading]);

  const fetchProviders = async () => {
    try {
      const [sttRes, llmRes, ttsRes] = await Promise.all([
        fetch("/api/providers/stt"),
        fetch("/api/providers/llm"),
        fetch("/api/providers/tts"),
      ]);

      const [sttData, llmData, ttsData] = await Promise.all([
        sttRes.json(),
        llmRes.json(),
        ttsRes.json(),
      ]);

      // Extract the providers object from the API response
      const sttProviders = sttData.providers || {};
      const llmProviders = llmData.providers || {};
      const ttsProviders = ttsData.providers || {};

      setProviders({ stt: sttProviders, llm: llmProviders, tts: ttsProviders });

      // Set default models/voices based on selected providers
      setFormData(prev => ({
        ...prev,
        stt_model: sttProviders.deepgram?.default_model || "",
        llm_model: llmProviders.openai?.default_model || "",
        tts_voice: ttsProviders.cartesia?.voices?.[0]?.value || "",
      }));
      
      setLoading(false);
    } catch (error) {
      console.error("Error fetching providers:", error);
      setLoading(false);
    }
  };

  const handleFieldChange = (field: keyof FormData, value: any) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
    setIsDirty(true);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const response = await fetch("/api/assistants", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...formData,
          hotel_id: DEMO_HOTEL_ID,
          is_active: true,
        }),
      });

      if (!response.ok) {
        throw new Error("Failed to create assistant");
      }

      const data = await response.json();
      setIsDirty(false);
      router.push(`/dashboard/assistants/${data.id}`);
    } catch (error) {
      console.error("Error creating assistant:", error);
      alert("Failed to create assistant");
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    router.push("/dashboard/assistants");
  };

  const scrollToSection = (tabId: string) => {
    setActiveTab(tabId);
    const element = document.getElementById(`section-${tabId}`);
    if (element) {
      const offset = 150;
      const elementPosition = element.getBoundingClientRect().top;
      const offsetPosition = elementPosition + window.pageYOffset - offset;
      window.scrollTo({
        top: offsetPosition,
        behavior: "smooth",
      });
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-gray-400">Loading configuration...</div>
      </div>
    );
  }

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
              <h1 className="text-2xl font-bold">Create New Assistant</h1>
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
      <div className="px-8 py-8 max-w-4xl space-y-12">
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
              value={formData.temperature || 0.7}
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
          <ProviderSelector
            label="TTS Provider"
            description="Service that converts text into natural-sounding voice"
            providerValue={formData.tts_provider || ""}
            modelValue={formData.tts_voice || ""}
            providers={Object.entries(providers.tts).map(([key, config]: [string, any]) => ({
              value: key,
              label: config.display_name || key,
            }))}
            models={formData.tts_provider && providers.tts[formData.tts_provider]?.voices 
              ? providers.tts[formData.tts_provider].voices.map((v: any) => ({
                  value: v.value,
                  label: v.label,
                }))
              : []}
            onProviderChange={(value) => {
              handleFieldChange("tts_provider", value);
              const defaultVoice = providers.tts[value]?.voices?.[0]?.value;
              if (defaultVoice) {
                handleFieldChange("tts_voice", defaultVoice);
              }
            }}
            onModelChange={(value) => handleFieldChange("tts_voice", value)}
          />
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
