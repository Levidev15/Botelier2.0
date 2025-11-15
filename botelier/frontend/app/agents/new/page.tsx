"use client";

import { useState } from "react";
import { Bot, ArrowLeft, Save } from "lucide-react";
import Link from "next/link";

const STT_PROVIDERS = [
  { id: "deepgram", name: "Deepgram", models: ["nova-3-general", "nova-2-general", "nova-2-meeting"] },
  { id: "openai_whisper", name: "OpenAI Whisper", models: ["whisper-1"] },
  { id: "assemblyai", name: "AssemblyAI", models: ["universal-streaming-english", "universal-streaming-multilingual"] },
  { id: "azure", name: "Azure Speech", models: ["default"] },
  { id: "google", name: "Google Speech-to-Text", models: ["default"] },
];

const LLM_PROVIDERS = [
  { id: "openai", name: "OpenAI", models: ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"] },
  { id: "anthropic", name: "Anthropic Claude", models: ["claude-3-5-sonnet-20241022", "claude-3-opus-20240229", "claude-3-haiku-20240307"] },
  { id: "google_gemini", name: "Google Gemini", models: ["gemini-2.0-flash-exp", "gemini-1.5-pro", "gemini-1.5-flash"] },
  { id: "azure_openai", name: "Azure OpenAI", models: ["gpt-4o", "gpt-4-turbo"] },
  { id: "groq", name: "Groq", models: ["llama-3.1-70b", "mixtral-8x7b"] },
];

const TTS_PROVIDERS = [
  {
    id: "cartesia",
    name: "Cartesia",
    voices: [
      { id: "71a7ad14-091c-4e8e-a314-022ece01c121", name: "British Reading Lady" },
      { id: "79a125e8-cd45-4c13-8a67-188112f4dd22", name: "British Narrator Lady" },
      { id: "a0e99841-438c-4a64-b679-ae501e7d6091", name: "Friendly Reading Man" },
    ],
  },
  {
    id: "elevenlabs",
    name: "ElevenLabs",
    voices: [
      { id: "21m00Tcm4TlvDq8ikWAM", name: "Rachel" },
      { id: "pNInz6obpgDQGcFmaJgB", name: "Adam" },
      { id: "EXAVITQu4vr4xnSDxMaL", name: "Bella" },
    ],
  },
  {
    id: "openai",
    name: "OpenAI TTS",
    voices: [
      { id: "alloy", name: "Alloy" },
      { id: "echo", name: "Echo" },
      { id: "nova", name: "Nova" },
      { id: "shimmer", name: "Shimmer" },
    ],
  },
];

export default function NewAgentPage() {
  const [formData, setFormData] = useState({
    name: "",
    description: "",
    sttProvider: "deepgram",
    sttModel: "nova-3-general",
    sttLanguage: "en",
    llmProvider: "openai",
    llmModel: "gpt-4o-mini",
    llmTemperature: 0.7,
    llmMaxTokens: 150,
    ttsProvider: "cartesia",
    ttsVoiceId: "71a7ad14-091c-4e8e-a314-022ece01c121",
    ttsSpeed: 1.0,
    systemPrompt: "You are a friendly hotel concierge assistant. Help guests with their inquiries, bookings, and provide information about the hotel amenities and local attractions.",
    greetingMessage: "Hello! Welcome to our hotel. How can I assist you today?",
    enableVad: true,
    enableInterruptions: true,
  });

  const selectedSTT = STT_PROVIDERS.find((p) => p.id === formData.sttProvider);
  const selectedLLM = LLM_PROVIDERS.find((p) => p.id === formData.llmProvider);
  const selectedTTS = TTS_PROVIDERS.find((p) => p.id === formData.ttsProvider);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    console.log("Creating agent:", formData);
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="bg-white shadow-sm border-b">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between h-16 items-center">
            <Link href="/agents" className="flex items-center">
              <Bot className="h-8 w-8 text-blue-600" />
              <span className="ml-2 text-2xl font-bold text-gray-900">Botelier</span>
            </Link>
            <Link
              href="/agents"
              className="inline-flex items-center text-gray-600 hover:text-gray-900"
            >
              <ArrowLeft className="h-5 w-5 mr-1" />
              Back to Agents
            </Link>
          </div>
        </div>
      </nav>

      <main className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-gray-900">Create Voice Agent</h1>
          <p className="text-gray-600 mt-1">
            Configure your hotel's conversational AI agent
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-6">
          <Section title="Basic Information">
            <Input
              label="Agent Name"
              id="name"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              placeholder="e.g., Concierge Agent"
              required
            />
            <Textarea
              label="Description"
              id="description"
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              placeholder="Brief description of this agent's purpose"
              rows={3}
            />
          </Section>

          <Section title="Speech-to-Text (STT)" description="Choose how the agent understands spoken input">
            <Select
              label="STT Provider"
              id="sttProvider"
              value={formData.sttProvider}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  sttProvider: e.target.value,
                  sttModel: STT_PROVIDERS.find((p) => p.id === e.target.value)?.models[0] || "",
                })
              }
              options={STT_PROVIDERS.map((p) => ({ value: p.id, label: p.name }))}
            />
            {selectedSTT && (
              <Select
                label="Model"
                id="sttModel"
                value={formData.sttModel}
                onChange={(e) => setFormData({ ...formData, sttModel: e.target.value })}
                options={selectedSTT.models.map((m) => ({ value: m, label: m }))}
              />
            )}
            <Select
              label="Language"
              id="sttLanguage"
              value={formData.sttLanguage}
              onChange={(e) => setFormData({ ...formData, sttLanguage: e.target.value })}
              options={[
                { value: "en", label: "English" },
                { value: "es", label: "Spanish" },
                { value: "fr", label: "French" },
                { value: "de", label: "German" },
              ]}
            />
          </Section>

          <Section title="Language Model (LLM)" description="Choose the AI brain for conversations">
            <Select
              label="LLM Provider"
              id="llmProvider"
              value={formData.llmProvider}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  llmProvider: e.target.value,
                  llmModel: LLM_PROVIDERS.find((p) => p.id === e.target.value)?.models[0] || "",
                })
              }
              options={LLM_PROVIDERS.map((p) => ({ value: p.id, label: p.name }))}
            />
            {selectedLLM && (
              <Select
                label="Model"
                id="llmModel"
                value={formData.llmModel}
                onChange={(e) => setFormData({ ...formData, llmModel: e.target.value })}
                options={selectedLLM.models.map((m) => ({ value: m, label: m }))}
              />
            )}
            <div className="grid grid-cols-2 gap-4">
              <Input
                label="Temperature"
                id="temperature"
                type="number"
                min="0"
                max="2"
                step="0.1"
                value={formData.llmTemperature}
                onChange={(e) => setFormData({ ...formData, llmTemperature: parseFloat(e.target.value) })}
                helpText="Higher = more creative (0-2)"
              />
              <Input
                label="Max Tokens"
                id="maxTokens"
                type="number"
                min="10"
                max="1000"
                value={formData.llmMaxTokens}
                onChange={(e) => setFormData({ ...formData, llmMaxTokens: parseInt(e.target.value) })}
                helpText="Response length limit"
              />
            </div>
          </Section>

          <Section title="Text-to-Speech (TTS)" description="Choose the agent's voice">
            <Select
              label="TTS Provider"
              id="ttsProvider"
              value={formData.ttsProvider}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  ttsProvider: e.target.value,
                  ttsVoiceId: TTS_PROVIDERS.find((p) => p.id === e.target.value)?.voices[0]?.id || "",
                })
              }
              options={TTS_PROVIDERS.map((p) => ({ value: p.id, label: p.name }))}
            />
            {selectedTTS && (
              <Select
                label="Voice"
                id="ttsVoiceId"
                value={formData.ttsVoiceId}
                onChange={(e) => setFormData({ ...formData, ttsVoiceId: e.target.value })}
                options={selectedTTS.voices.map((v) => ({ value: v.id, label: v.name }))}
              />
            )}
            <Input
              label="Speech Speed"
              id="ttsSpeed"
              type="number"
              min="0.5"
              max="2"
              step="0.1"
              value={formData.ttsSpeed}
              onChange={(e) => setFormData({ ...formData, ttsSpeed: parseFloat(e.target.value) })}
              helpText="Normal speed = 1.0"
            />
          </Section>

          <Section title="Conversation Settings" description="Configure how the agent behaves">
            <Textarea
              label="System Prompt"
              id="systemPrompt"
              value={formData.systemPrompt}
              onChange={(e) => setFormData({ ...formData, systemPrompt: e.target.value })}
              rows={4}
              helpText="Instructions that define the agent's personality and behavior"
              required
            />
            <Input
              label="Greeting Message"
              id="greetingMessage"
              value={formData.greetingMessage}
              onChange={(e) => setFormData({ ...formData, greetingMessage: e.target.value })}
              placeholder="What the agent says first"
              required
            />
          </Section>

          <Section title="Advanced Features">
            <div className="space-y-3">
              <Checkbox
                label="Enable Voice Activity Detection (VAD)"
                id="enableVad"
                checked={formData.enableVad}
                onChange={(e) => setFormData({ ...formData, enableVad: e.target.checked })}
                helpText="Automatically detect when user starts/stops speaking"
              />
              <Checkbox
                label="Enable Interruptions"
                id="enableInterruptions"
                checked={formData.enableInterruptions}
                onChange={(e) => setFormData({ ...formData, enableInterruptions: e.target.checked })}
                helpText="Allow users to interrupt the agent mid-sentence"
              />
            </div>
          </Section>

          <div className="flex justify-end space-x-4 pt-6 border-t">
            <Link
              href="/agents"
              className="px-6 py-2 border border-gray-300 rounded-md text-gray-700 hover:bg-gray-50 transition"
            >
              Cancel
            </Link>
            <button
              type="submit"
              className="inline-flex items-center px-6 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition"
            >
              <Save className="h-5 w-5 mr-2" />
              Create Agent
            </button>
          </div>
        </form>
      </main>
    </div>
  );
}

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-white rounded-lg shadow-md p-6">
      <div className="mb-4">
        <h2 className="text-xl font-semibold text-gray-900">{title}</h2>
        {description && <p className="text-sm text-gray-600 mt-1">{description}</p>}
      </div>
      <div className="space-y-4">{children}</div>
    </div>
  );
}

function Input({
  label,
  id,
  type = "text",
  value,
  onChange,
  placeholder,
  required,
  helpText,
  min,
  max,
  step,
}: {
  label: string;
  id: string;
  type?: string;
  value: string | number;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  placeholder?: string;
  required?: boolean;
  helpText?: string;
  min?: string;
  max?: string;
  step?: string;
}) {
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium text-gray-700 mb-1">
        {label}
        {required && <span className="text-red-500 ml-1">*</span>}
      </label>
      <input
        type={type}
        id={id}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        required={required}
        min={min}
        max={max}
        step={step}
        className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
      />
      {helpText && <p className="mt-1 text-xs text-gray-500">{helpText}</p>}
    </div>
  );
}

function Textarea({
  label,
  id,
  value,
  onChange,
  rows = 3,
  placeholder,
  required,
  helpText,
}: {
  label: string;
  id: string;
  value: string;
  onChange: (e: React.ChangeEvent<HTMLTextAreaElement>) => void;
  rows?: number;
  placeholder?: string;
  required?: boolean;
  helpText?: string;
}) {
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium text-gray-700 mb-1">
        {label}
        {required && <span className="text-red-500 ml-1">*</span>}
      </label>
      <textarea
        id={id}
        value={value}
        onChange={onChange}
        rows={rows}
        placeholder={placeholder}
        required={required}
        className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
      />
      {helpText && <p className="mt-1 text-xs text-gray-500">{helpText}</p>}
    </div>
  );
}

function Select({
  label,
  id,
  value,
  onChange,
  options,
  required,
}: {
  label: string;
  id: string;
  value: string;
  onChange: (e: React.ChangeEvent<HTMLSelectElement>) => void;
  options: Array<{ value: string; label: string }>;
  required?: boolean;
}) {
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium text-gray-700 mb-1">
        {label}
        {required && <span className="text-red-500 ml-1">*</span>}
      </label>
      <select
        id={id}
        value={value}
        onChange={onChange}
        required={required}
        className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}

function Checkbox({
  label,
  id,
  checked,
  onChange,
  helpText,
}: {
  label: string;
  id: string;
  checked: boolean;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  helpText?: string;
}) {
  return (
    <div className="flex items-start">
      <input
        type="checkbox"
        id={id}
        checked={checked}
        onChange={onChange}
        className="mt-1 h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
      />
      <div className="ml-3">
        <label htmlFor={id} className="text-sm font-medium text-gray-700">
          {label}
        </label>
        {helpText && <p className="text-xs text-gray-500 mt-0.5">{helpText}</p>}
      </div>
    </div>
  );
}
