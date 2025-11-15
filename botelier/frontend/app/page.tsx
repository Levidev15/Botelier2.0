"use client";

import Link from "next/link";
import { Bot, Settings, Phone, BarChart, Users } from "lucide-react";

export default function Home() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100">
      <nav className="bg-white shadow-sm border-b">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between h-16 items-center">
            <div className="flex items-center">
              <Bot className="h-8 w-8 text-blue-600" />
              <span className="ml-2 text-2xl font-bold text-gray-900">Botelier</span>
            </div>
            <div className="flex space-x-4">
              <Link
                href="/agents"
                className="inline-flex items-center px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition"
              >
                Go to Dashboard
              </Link>
            </div>
          </div>
        </div>
      </nav>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
        <div className="text-center mb-16">
          <h1 className="text-5xl font-bold text-gray-900 mb-4">
            Hotel Voice AI Platform
          </h1>
          <p className="text-xl text-gray-600 max-w-2xl mx-auto">
            Create and manage conversational AI agents for your hotel. Handle guest inquiries,
            bookings, and concierge services with intelligent voice assistants.
          </p>
        </div>

        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-8 mb-12">
          <FeatureCard
            icon={<Bot className="h-10 w-10 text-blue-600" />}
            title="Voice Agents"
            description="Configure custom AI agents with your choice of speech recognition, language models, and text-to-speech providers."
          />
          <FeatureCard
            icon={<Settings className="h-10 w-10 text-blue-600" />}
            title="Easy Configuration"
            description="Simple interface to customize agent behavior, prompts, voices, and integrate with your hotel systems."
          />
          <FeatureCard
            icon={<Phone className="h-10 w-10 text-blue-600" />}
            title="Phone Integration"
            description="Connect agents to phone numbers via Twilio for seamless guest communication."
          />
          <FeatureCard
            icon={<BarChart className="h-10 w-10 text-blue-600" />}
            title="Analytics"
            description="Track call volumes, transcripts, and agent performance with detailed analytics."
          />
          <FeatureCard
            icon={<Users className="h-10 w-10 text-blue-600" />}
            title="Multi-tenant"
            description="Secure, isolated environments for each hotel with role-based access control."
          />
          <FeatureCard
            icon={<Bot className="h-10 w-10 text-blue-600" />}
            title="40+ AI Providers"
            description="Choose from Deepgram, OpenAI, Anthropic, ElevenLabs, Cartesia, and many more."
          />
        </div>

        <div className="bg-white rounded-lg shadow-lg p-8 text-center">
          <h2 className="text-3xl font-bold text-gray-900 mb-4">
            Supported AI Providers
          </h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-8">
            <ProviderBadge name="Deepgram" />
            <ProviderBadge name="OpenAI" />
            <ProviderBadge name="Anthropic Claude" />
            <ProviderBadge name="Google Gemini" />
            <ProviderBadge name="Cartesia" />
            <ProviderBadge name="ElevenLabs" />
            <ProviderBadge name="AssemblyAI" />
            <ProviderBadge name="Azure" />
          </div>
          <p className="mt-6 text-gray-600">
            + 30 more providers including AWS, Groq, Mistral, and more
          </p>
        </div>
      </main>
    </div>
  );
}

function FeatureCard({
  icon,
  title,
  description,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
}) {
  return (
    <div className="bg-white rounded-lg shadow-md p-6 hover:shadow-lg transition">
      <div className="mb-4">{icon}</div>
      <h3 className="text-xl font-semibold text-gray-900 mb-2">{title}</h3>
      <p className="text-gray-600">{description}</p>
    </div>
  );
}

function ProviderBadge({ name }: { name: string }) {
  return (
    <div className="bg-gray-100 rounded-md px-4 py-2 text-sm font-medium text-gray-700">
      {name}
    </div>
  );
}
