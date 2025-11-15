"use client";

import { useState } from "react";
import { ArrowLeft, Save, Sparkles } from "lucide-react";
import Link from "next/link";

const STT_PROVIDERS = [
  { id: "deepgram", name: "Deepgram", models: ["nova-3-general", "nova-2-general"] },
  { id: "openai_whisper", name: "OpenAI Whisper", models: ["whisper-1"] },
  { id: "assemblyai", name: "AssemblyAI", models: ["universal-streaming-english"] },
];

const LLM_PROVIDERS = [
  { id: "openai", name: "OpenAI", models: ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"] },
  { id: "anthropic", name: "Anthropic", models: ["claude-3-5-sonnet-20241022", "claude-3-opus"] },
  { id: "google_gemini", name: "Google Gemini", models: ["gemini-2.0-flash-exp", "gemini-1.5-pro"] },
];

const TTS_PROVIDERS = [
  {
    id: "cartesia",
    name: "Cartesia",
    voices: [
      { id: "71a7ad14-091c-4e8e-a314-022ece01c121", name: "British Reading Lady" },
      { id: "a0e99841-438c-4a64-b679-ae501e7d6091", name: "Friendly Reading Man" },
    ],
  },
  {
    id: "elevenlabs",
    name: "ElevenLabs",
    voices: [
      { id: "21m00Tcm4TlvDq8ikWAM", name: "Rachel" },
      { id: "pNInz6obpgDQGcFmaJgB", name: "Adam" },
    ],
  },
];

export default function NewAssistantPage() {
  const [formData, setFormData] = useState({
    name: "",
    sttProvider: "deepgram",
    sttModel: "nova-3-general",
    llmProvider: "openai",
    llmModel: "gpt-4o-mini",
    llmTemperature: 0.7,
    ttsProvider: "cartesia",
    ttsVoiceId: "71a7ad14-091c-4e8e-a314-022ece01c121",
    systemPrompt: "You are a friendly hotel concierge assistant.",
    greetingMessage: "Hello! How can I assist you today?",
  });

  const selectedLLM = LLM_PROVIDERS.find((p) => p.id === formData.llmProvider);
  const selectedTTS = TTS_PROVIDERS.find((p) => p.id === formData.ttsProvider);

  return (
    <div className="h-full overflow-auto">
      <div className="border-b border-gray-800 bg-[#0a0a0a] sticky top-0 z-10">
        <div className="px-8 py-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-4">
              <Link
                href="/dashboard/assistants"
                className="p-2 hover:bg-gray-800 rounded-lg transition"
              >
                <ArrowLeft className="h-5 w-5" />
              </Link>
              <div>
                <h1 className="text-2xl font-bold">Create Assistant</h1>
                <p className="text-sm text-gray-400 mt-1">
                  Configure your voice AI assistant
                </p>
              </div>
            </div>
            <button className="inline-flex items-center px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg transition text-sm font-medium">
              <Save className="h-4 w-4 mr-2" />
              Save Assistant
            </button>
          </div>
        </div>
      </div>

      <div className="p-8 max-w-4xl">
        <div className="space-y-6">
          <Section title="Basic Information">
            <Input
              label="Assistant Name"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              placeholder="e.g., Hotel Concierge"
            />
          </Section>

          <Section title="Model" icon={<Sparkles className="h-5 w-5 text-blue-400" />}>
            <div className="grid grid-cols-2 gap-4">
              <Select
                label="Provider"
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
                  value={formData.llmModel}
                  onChange={(e) => setFormData({ ...formData, llmModel: e.target.value })}
                  options={selectedLLM.models.map((m) => ({ value: m, label: m }))}
                />
              )}
            </div>
            <Input
              label="Temperature"
              type="number"
              min="0"
              max="2"
              step="0.1"
              value={formData.llmTemperature}
              onChange={(e) => setFormData({ ...formData, llmTemperature: parseFloat(e.target.value) })}
              helpText="Controls randomness. Higher = more creative (0-2)"
            />
          </Section>

          <Section title="Voice Configuration">
            <div className="grid grid-cols-2 gap-4">
              <Select
                label="Voice Provider"
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
                  value={formData.ttsVoiceId}
                  onChange={(e) => setFormData({ ...formData, ttsVoiceId: e.target.value })}
                  options={selectedTTS.voices.map((v) => ({ value: v.id, label: v.name }))}
                />
              )}
            </div>
          </Section>

          <Section title="System Prompt">
            <Textarea
              value={formData.systemPrompt}
              onChange={(e) => setFormData({ ...formData, systemPrompt: e.target.value })}
              rows={6}
              placeholder="Define how your assistant should behave..."
            />
          </Section>

          <Section title="First Message">
            <Input
              value={formData.greetingMessage}
              onChange={(e) => setFormData({ ...formData, greetingMessage: e.target.value })}
              placeholder="What the assistant says when call starts"
            />
          </Section>
        </div>
      </div>
    </div>
  );
}

function Section({
  title,
  icon,
  children,
}: {
  title: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-[#141414] border border-gray-800 rounded-lg p-6">
      <div className="flex items-center space-x-2 mb-4">
        {icon}
        <h2 className="text-lg font-semibold">{title}</h2>
      </div>
      <div className="space-y-4">{children}</div>
    </div>
  );
}

function Input({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
  min,
  max,
  step,
  helpText,
}: {
  label?: string;
  value: string | number;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  placeholder?: string;
  type?: string;
  min?: string;
  max?: string;
  step?: string;
  helpText?: string;
}) {
  return (
    <div>
      {label && <label className="block text-sm font-medium text-gray-300 mb-2">{label}</label>}
      <input
        type={type}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        min={min}
        max={max}
        step={step}
        className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
      />
      {helpText && <p className="mt-1.5 text-xs text-gray-500">{helpText}</p>}
    </div>
  );
}

function Textarea({
  value,
  onChange,
  rows = 3,
  placeholder,
}: {
  value: string;
  onChange: (e: React.ChangeEvent<HTMLTextAreaElement>) => void;
  rows?: number;
  placeholder?: string;
}) {
  return (
    <textarea
      value={value}
      onChange={onChange}
      rows={rows}
      placeholder={placeholder}
      className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm font-mono"
    />
  );
}

function Select({
  label,
  value,
  onChange,
  options,
}: {
  label?: string;
  value: string;
  onChange: (e: React.ChangeEvent<HTMLSelectElement>) => void;
  options: Array<{ value: string; label: string }>;
}) {
  return (
    <div>
      {label && <label className="block text-sm font-medium text-gray-300 mb-2">{label}</label>}
      <select
        value={value}
        onChange={onChange}
        className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm"
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
