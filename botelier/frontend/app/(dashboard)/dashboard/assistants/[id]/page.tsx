"use client";

import { useState, useEffect, useRef } from "react";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, Info, Mic, Brain, Wrench, Phone, BookOpen } from "lucide-react";
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
  tts_voice: string | null;
  system_prompt: string | null;
  first_message: string | null;
  language: string;
  temperature: string;
  max_tokens: number | null;
  is_active: boolean;
}

const TABS: Tab[] = [
  { id: "info", label: "Info", icon: <Info className="h-4 w-4" /> },
  { id: "voice", label: "Voice", icon: <Mic className="h-4 w-4" /> },
  { id: "model", label: "Model", icon: <Brain className="h-4 w-4" /> },
  { id: "tools", label: "Tools", icon: <Wrench className="h-4 w-4" /> },
  { id: "phone", label: "Phone Numbers", icon: <Phone className="h-4 w-4" /> },
  { id: "knowledge", label: "Knowledge", icon: <BookOpen className="h-4 w-4" /> },
];

// Mock provider data (will be fetched from backend later)
const STT_PROVIDERS = [
  { value: "deepgram", label: "Deepgram" },
  { value: "openai", label: "OpenAI Whisper" },
  { value: "assemblyai", label: "AssemblyAI" },
];

const LLM_PROVIDERS = [
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Anthropic" },
  { value: "gemini", label: "Google Gemini" },
];

const TTS_PROVIDERS = [
  { value: "cartesia", label: "Cartesia" },
  { value: "elevenlabs", label: "ElevenLabs" },
  { value: "openai", label: "OpenAI TTS" },
];

export default function AssistantDetailPage() {
  const params = useParams();
  const router = useRouter();
  const [activeTab, setActiveTab] = useState("info");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [isDirty, setIsDirty] = useState(false);
  
  const [assistant, setAssistant] = useState<Assistant | null>(null);
  const [formData, setFormData] = useState<Partial<Assistant>>({});
  
  const sectionRefs = useRef<{ [key: string]: HTMLElement | null }>({});

  useEffect(() => {
    fetchAssistant();
  }, [params.id]);

  // Track active tab based on scroll position using IntersectionObserver
  useEffect(() => {
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
      
      // Find the section closest to the top of the viewport
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
      root: null,
      rootMargin: '-100px 0px -50% 0px',
      threshold: [0, 0.25, 0.5, 0.75, 1],
    };

    TABS.forEach(tab => {
      const element = document.getElementById(`section-${tab.id}`);
      if (element) {
        sectionRefs.current[tab.id] = element;
        const observer = new IntersectionObserver(observerCallback, observerOptions);
        observer.observe(element);
        observers.push(observer);
      }
    });

    return () => {
      observers.forEach(observer => observer.disconnect());
    };
  }, [assistant]);

  const fetchAssistant = async () => {
    try {
      const response = await fetch(`/api/assistants/${params.id}`);
      if (!response.ok) throw new Error("Failed to fetch assistant");
      const data = await response.json();
      setAssistant(data);
      setFormData(data);
    } catch (error) {
      console.error("Failed to fetch assistant:", error);
    } finally {
      setLoading(false);
    }
  };

  const handleFieldChange = (field: keyof Assistant, value: any) => {
    setFormData((prev) => {
      const updated = { ...prev, [field]: value };
      
      // Check if form data actually differs from original assistant data
      if (assistant) {
        const hasChanges = Object.keys(updated).some(key => {
          const k = key as keyof Assistant;
          return updated[k] !== assistant[k];
        });
        setIsDirty(hasChanges);
      }
      
      return updated;
    });
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const response = await fetch(`/api/assistants/${params.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(formData),
      });
      if (!response.ok) throw new Error("Failed to save");
      const updated = await response.json();
      setAssistant(updated);
      setFormData(updated);
      setIsDirty(false);
    } catch (error) {
      console.error("Failed to save:", error);
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    if (assistant) {
      setFormData(assistant);
      setIsDirty(false);
    }
  };

  const scrollToSection = (tabId: string) => {
    setActiveTab(tabId);
    const element = document.getElementById(`section-${tabId}`);
    if (element) {
      const offset = 150; // Header (90px) + Tab bar (60px) + padding
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
        <div className="text-gray-400">Loading assistant...</div>
      </div>
    );
  }

  if (!assistant) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-gray-400">Assistant not found</div>
      </div>
    );
  }

  return (
    <div className="h-full pb-20">
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
              <h1 className="text-2xl font-bold">{assistant.name}</h1>
              <p className="text-sm text-gray-400 mt-1">
                Configure your voice assistant
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Tab Navigation - positioned below header */}
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

        {/* Voice Section */}
        <FormSection
          id="section-voice"
          title="Voice Configuration"
          description="Select the AI providers for speech recognition, language processing, and text-to-speech"
        >
          <ProviderSelector
            label="Speech-to-Text (STT)"
            description="Converts caller's voice into text"
            providerValue={formData.stt_provider || ""}
            modelValue={formData.stt_model || ""}
            providers={STT_PROVIDERS}
            models={[]}
            onProviderChange={(value) => handleFieldChange("stt_provider", value)}
            onModelChange={(value) => handleFieldChange("stt_model", value)}
          />

          <ProviderSelector
            label="Language Model (LLM)"
            description="Powers the conversational intelligence"
            providerValue={formData.llm_provider || ""}
            modelValue={formData.llm_model || ""}
            providers={LLM_PROVIDERS}
            models={[]}
            onProviderChange={(value) => handleFieldChange("llm_provider", value)}
            onModelChange={(value) => handleFieldChange("llm_model", value)}
          />

          <ProviderSelector
            label="Text-to-Speech (TTS)"
            description="Converts responses into natural-sounding voice"
            providerValue={formData.tts_provider || ""}
            modelValue={formData.tts_voice || ""}
            providers={TTS_PROVIDERS}
            models={[]}
            onProviderChange={(value) => handleFieldChange("tts_provider", value)}
            onModelChange={(value) => handleFieldChange("tts_voice", value)}
          />
        </FormSection>

        {/* Model Section */}
        <FormSection
          id="section-model"
          title="Model Configuration"
          description="Configure how the AI model behaves and responds"
        >
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
              value={parseFloat(formData.temperature || "0.7")}
              onChange={(e) => handleFieldChange("temperature", e.target.value)}
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

        {/* Tools Section */}
        <FormSection
          id="section-tools"
          title="Tools & Functions"
          description="Enable tools for call transfers, API integrations, and more"
        >
          <div className="bg-gray-800/30 border border-gray-700 rounded-lg p-6 text-center">
            <Wrench className="h-12 w-12 text-gray-600 mx-auto mb-3" />
            <p className="text-gray-400 text-sm mb-4">
              No tools configured yet
            </p>
            <Link
              href="/dashboard/tools"
              className="inline-flex items-center px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg transition text-sm font-medium"
            >
              Manage Tools
            </Link>
          </div>
        </FormSection>

        {/* Phone Numbers Section */}
        <FormSection
          id="section-phone"
          title="Phone Numbers"
          description="Phone numbers assigned to this assistant"
        >
          <div className="bg-gray-800/30 border border-gray-700 rounded-lg p-6 text-center">
            <Phone className="h-12 w-12 text-gray-600 mx-auto mb-3" />
            <p className="text-gray-400 text-sm mb-4">
              No phone numbers assigned
            </p>
            <Link
              href="/dashboard/phone-numbers"
              className="inline-flex items-center px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg transition text-sm font-medium"
            >
              Manage Phone Numbers
            </Link>
          </div>
        </FormSection>

        {/* Knowledge Section */}
        <FormSection
          id="section-knowledge"
          title="Knowledge Base"
          description="Q&A entries the assistant can reference during conversations"
        >
          <div className="bg-gray-800/30 border border-gray-700 rounded-lg p-6 text-center">
            <BookOpen className="h-12 w-12 text-gray-600 mx-auto mb-3" />
            <p className="text-gray-400 text-sm mb-4">
              No knowledge entries configured
            </p>
            <Link
              href="/dashboard/knowledge-bases"
              className="inline-flex items-center px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg transition text-sm font-medium"
            >
              Manage Knowledge Base
            </Link>
          </div>
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
