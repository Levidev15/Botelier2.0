"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Phone, MessageSquare, BarChart3, Users, Building2, Zap, Shield,
  Star, ArrowRight, CheckCircle, Headphones, Sparkles, TrendingUp,
  Settings, Layers, GitBranch, Mic,
} from "lucide-react";

// ─── Nav ──────────────────────────────────────────────────────────────────────

function Nav({ scrolled }: { scrolled: boolean }) {
  return (
    <nav
      className={`fixed top-0 left-0 right-0 z-50 transition-all duration-300 ${
        scrolled
          ? "bg-[#050507]/90 backdrop-blur-md border-b border-white/[0.06]"
          : "bg-transparent"
      }`}
    >
      <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center shadow-lg">
            <span className="text-sm font-bold text-white" style={{ fontFamily: "'Syne', sans-serif" }}>B</span>
          </div>
          <span className="text-white font-semibold tracking-tight" style={{ fontFamily: "'Syne', sans-serif" }}>
            Botelier
          </span>
        </div>
        <div className="flex items-center gap-3">
          <a
            href="/login"
            className="px-4 py-2 text-sm text-gray-400 hover:text-white transition-colors"
          >
            Log in
          </a>
          <a
            href="mailto:sales@botelier.ai"
            className="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-500 text-white rounded-lg transition-all font-medium shadow-lg shadow-blue-900/30"
          >
            Contact Sales
          </a>
        </div>
      </div>
    </nav>
  );
}

// ─── Hero ─────────────────────────────────────────────────────────────────────

function Hero() {
  return (
    <section className="relative min-h-screen flex items-center justify-center overflow-hidden pt-20">
      <div className="absolute inset-0 pointer-events-none">
        <div
          className="absolute inset-0"
          style={{
            backgroundImage:
              "linear-gradient(rgba(255,255,255,0.018) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.018) 1px, transparent 1px)",
            backgroundSize: "64px 64px",
          }}
        />
        <div
          className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[900px] h-[900px] rounded-full"
          style={{
            background:
              "radial-gradient(circle, rgba(59,130,246,0.10) 0%, rgba(99,102,241,0.06) 45%, transparent 70%)",
          }}
        />
        <div
          className="absolute top-0 left-0 right-0 h-40"
          style={{ background: "linear-gradient(to bottom, #050507, transparent)" }}
        />
        <div
          className="absolute bottom-0 left-0 right-0 h-40"
          style={{ background: "linear-gradient(to top, #050507, transparent)" }}
        />
      </div>

      <div className="relative z-10 max-w-5xl mx-auto px-6 text-center">
        <div
          className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full border border-blue-500/25 bg-blue-500/10 text-blue-400 text-xs font-semibold mb-10 tracking-widest uppercase"
          style={{ fontFamily: "'Syne', sans-serif" }}
        >
          <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />
          AI-Powered Hospitality Communications
        </div>

        <h1
          className="text-[clamp(3rem,9vw,6.5rem)] font-semibold text-white mb-7 tracking-tight"
          style={{ fontFamily: "'Cormorant Garamond', serif", lineHeight: 1.04 }}
        >
          Turn Every Guest{" "}
          <span
            style={{
              background: "linear-gradient(135deg, #60a5fa 20%, #818cf8 80%)",
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
            }}
          >
            Interaction
          </span>
          <br />
          Into Excellence
        </h1>

        <p
          className="text-lg text-gray-400 max-w-2xl mx-auto mb-12 leading-relaxed"
          style={{ fontFamily: "'DM Sans', sans-serif" }}
        >
          Botelier is a multichannel AI platform that handles voice calls and SMS
          across every stage of the guest journey — so your team can focus on
          delivering exceptional hospitality.
        </p>

        <div className="flex items-center justify-center gap-4 flex-wrap">
          <a
            href="mailto:sales@botelier.ai"
            className="inline-flex items-center gap-2 px-7 py-3.5 bg-blue-600 hover:bg-blue-500 text-white rounded-xl font-medium transition-all hover:scale-[1.03] shadow-xl shadow-blue-900/40"
            style={{ fontFamily: "'DM Sans', sans-serif" }}
          >
            Contact Sales
            <ArrowRight className="h-4 w-4" />
          </a>
          <a
            href="/login"
            className="inline-flex items-center gap-2 px-7 py-3.5 border border-white/10 hover:border-white/20 text-gray-300 hover:text-white rounded-xl font-medium transition-all"
            style={{ fontFamily: "'DM Sans', sans-serif" }}
          >
            Log In
          </a>
        </div>

        <div
          className="mt-20 flex items-center justify-center gap-10 flex-wrap"
          style={{ fontFamily: "'DM Sans', sans-serif" }}
        >
          {[
            { label: "Available", value: "24 / 7" },
            { label: "Response Time", value: "< 1s" },
            { label: "Languages", value: "30+" },
            { label: "Departments", value: "10+" },
          ].map((s) => (
            <div key={s.label} className="text-center">
              <div
                className="text-3xl font-bold text-white mb-0.5"
                style={{ fontFamily: "'Syne', sans-serif" }}
              >
                {s.value}
              </div>
              <div className="text-xs text-gray-600 tracking-wide">{s.label}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ─── Guest Journey ────────────────────────────────────────────────────────────

function GuestJourney() {
  const phases = [
    {
      num: "01",
      label: "Pre-Arrival",
      icon: MessageSquare,
      border: "border-blue-500/20",
      bg: "from-blue-500/10 to-blue-600/[0.03]",
      iconBg: "bg-blue-500/10 text-blue-400",
      items: [
        "Reservation confirmations & modifications",
        "Special request handling",
        "Pre-arrival SMS check-ins",
        "FAQ & amenity information",
        "Upsell opportunity detection",
      ],
    },
    {
      num: "02",
      label: "Arrival",
      icon: Mic,
      border: "border-indigo-500/20",
      bg: "from-indigo-500/10 to-indigo-600/[0.03]",
      iconBg: "bg-indigo-500/10 text-indigo-400",
      items: [
        "Check-in status & room notifications",
        "Welcome messages via SMS",
        "Valet & parking coordination",
        "Early check-in request routing",
        "Loyalty recognition prompts",
      ],
    },
    {
      num: "03",
      label: "In-Stay",
      icon: Headphones,
      border: "border-violet-500/20",
      bg: "from-violet-500/10 to-violet-600/[0.03]",
      iconBg: "bg-violet-500/10 text-violet-400",
      items: [
        "24/7 AI concierge voice line",
        "Maintenance & housekeeping requests",
        "F&B and room service orders",
        "Local recommendations & bookings",
        "Complaint resolution & escalation",
      ],
    },
    {
      num: "04",
      label: "Post-Stay",
      icon: Star,
      border: "border-purple-500/20",
      bg: "from-purple-500/10 to-purple-600/[0.03]",
      iconBg: "bg-purple-500/10 text-purple-400",
      items: [
        "Automated thank-you follow-ups",
        "Review request campaigns",
        "Loyalty program enrollment",
        "Return stay offers",
        "Post-stay feedback collection",
      ],
    },
  ];

  return (
    <section className="py-32 px-6" style={{ fontFamily: "'DM Sans', sans-serif" }}>
      <div className="max-w-7xl mx-auto">
        <div className="text-center mb-16">
          <p
            className="text-xs font-semibold tracking-[0.2em] uppercase text-blue-400 mb-4"
            style={{ fontFamily: "'Syne', sans-serif" }}
          >
            Guest Journey
          </p>
          <h2
            className="text-4xl md:text-5xl font-semibold text-white mb-4"
            style={{ fontFamily: "'Cormorant Garamond', serif", lineHeight: 1.1 }}
          >
            Every touchpoint,
            <br />
            intelligently handled
          </h2>
          <p className="text-gray-400 max-w-xl mx-auto">
            From the moment a guest discovers your property to their next return
            visit, Botelier manages communications end-to-end.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {phases.map((phase) => (
            <div
              key={phase.num}
              className={`relative rounded-2xl border ${phase.border} bg-gradient-to-b ${phase.bg} p-6 overflow-hidden`}
            >
              <div className="flex items-start justify-between mb-6">
                <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${phase.iconBg}`}>
                  <phase.icon className="h-5 w-5" />
                </div>
                <span
                  className="text-5xl font-bold text-white/[0.06] select-none"
                  style={{ fontFamily: "'Syne', sans-serif" }}
                >
                  {phase.num}
                </span>
              </div>
              <h3
                className="text-base font-semibold text-white mb-4"
                style={{ fontFamily: "'Syne', sans-serif" }}
              >
                {phase.label}
              </h3>
              <ul className="space-y-2.5">
                {phase.items.map((item) => (
                  <li key={item} className="flex items-start gap-2 text-sm text-gray-400">
                    <CheckCircle className="h-3.5 w-3.5 mt-0.5 flex-shrink-0 opacity-40" />
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ─── Use Cases ────────────────────────────────────────────────────────────────

function UseCases() {
  const cases = [
    {
      icon: Phone,
      title: "Inbound Voice AI",
      desc: "An intelligent AI agent answers every call, handles FAQs, takes requests, and routes complex issues to the right human — 24/7, in any language.",
      tags: ["Call handling", "Warm transfer", "Multi-language"],
    },
    {
      icon: MessageSquare,
      title: "Two-Way SMS",
      desc: "Engage guests over SMS with personalized, context-aware conversations. Booking confirmations, in-stay requests, and follow-ups — automated.",
      tags: ["Reservations", "Concierge", "Follow-ups"],
    },
    {
      icon: TrendingUp,
      title: "AI Quality Scoring",
      desc: "Every interaction is automatically scored for resolution, tone, and efficiency. Identify training gaps and surface what great looks like.",
      tags: ["ACW automation", "Dispositions", "QA scores"],
    },
    {
      icon: GitBranch,
      title: "Visual Flow Editor",
      desc: "Build complex conversation flows without code using a drag-and-drop editor. Version control, simulation, and live deployment built in.",
      tags: ["No-code", "Version control", "Live simulation"],
    },
    {
      icon: Zap,
      title: "Warm Transfers",
      desc: "When a guest needs a human, the AI hands off seamlessly — with full context — to the right team member or department, every time.",
      tags: ["Human handoff", "Context passing", "Department routing"],
    },
    {
      icon: BarChart3,
      title: "Real-Time Analytics",
      desc: "Dashboards built for hospitality operations — call volume, resolution rates, AI handling %, and custom KPIs across all your properties.",
      tags: ["Custom dashboards", "Exports", "Multi-property"],
    },
  ];

  return (
    <section
      className="py-32 px-6 relative"
      style={{ fontFamily: "'DM Sans', sans-serif" }}
    >
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background:
            "radial-gradient(ellipse at 50% 0%, rgba(59,130,246,0.04) 0%, transparent 60%)",
        }}
      />
      <div className="relative max-w-7xl mx-auto">
        <div className="text-center mb-16">
          <p
            className="text-xs font-semibold tracking-[0.2em] uppercase text-blue-400 mb-4"
            style={{ fontFamily: "'Syne', sans-serif" }}
          >
            Use Cases
          </p>
          <h2
            className="text-4xl md:text-5xl font-semibold text-white mb-4"
            style={{ fontFamily: "'Cormorant Garamond', serif", lineHeight: 1.1 }}
          >
            One platform.
            <br />
            Every channel.
          </h2>
          <p className="text-gray-400 max-w-xl mx-auto">
            Voice, SMS, and analytics — unified under a single AI layer built
            specifically for the demands of hospitality.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {cases.map((c) => (
            <div
              key={c.title}
              className="rounded-2xl border border-white/[0.06] bg-white/[0.02] hover:bg-white/[0.04] hover:border-white/[0.10] p-6 transition-all"
            >
              <div className="w-10 h-10 rounded-xl bg-blue-500/10 flex items-center justify-center mb-5">
                <c.icon className="h-5 w-5 text-blue-400" />
              </div>
              <h3
                className="text-base font-semibold text-white mb-2"
                style={{ fontFamily: "'Syne', sans-serif" }}
              >
                {c.title}
              </h3>
              <p className="text-sm text-gray-400 leading-relaxed mb-5">{c.desc}</p>
              <div className="flex flex-wrap gap-1.5">
                {c.tags.map((tag) => (
                  <span
                    key={tag}
                    className="px-2.5 py-0.5 rounded-full text-xs border border-white/[0.07] text-gray-500"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ─── Departments ──────────────────────────────────────────────────────────────

function Departments() {
  const depts = [
    { name: "Front Desk", icon: Building2 },
    { name: "Reservations", icon: Phone },
    { name: "Concierge", icon: Star },
    { name: "Food & Beverage", icon: Sparkles },
    { name: "Maintenance & Engineering", icon: Settings },
    { name: "Housekeeping", icon: Layers },
    { name: "Spa & Wellness", icon: Shield },
    { name: "Guest Services", icon: Headphones },
    { name: "Sales & Events", icon: TrendingUp },
    { name: "Revenue Management", icon: BarChart3 },
    { name: "Security", icon: Shield },
    { name: "Loyalty & CRM", icon: Users },
  ];

  return (
    <section
      className="py-32 px-6 relative overflow-hidden"
      style={{ fontFamily: "'DM Sans', sans-serif" }}
    >
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background:
            "radial-gradient(ellipse at 50% 50%, rgba(59,130,246,0.035) 0%, transparent 65%)",
        }}
      />
      <div className="relative max-w-7xl mx-auto">
        <div className="text-center mb-14">
          <p
            className="text-xs font-semibold tracking-[0.2em] uppercase text-blue-400 mb-4"
            style={{ fontFamily: "'Syne', sans-serif" }}
          >
            Departments Supported
          </p>
          <h2
            className="text-4xl md:text-5xl font-semibold text-white mb-4"
            style={{ fontFamily: "'Cormorant Garamond', serif", lineHeight: 1.1 }}
          >
            Built for every team
            <br />
            on property
          </h2>
          <p className="text-gray-400 max-w-xl mx-auto">
            Botelier connects to any department, routing calls and messages
            intelligently based on guest needs and your property structure.
          </p>
        </div>

        <div className="flex flex-wrap justify-center gap-3 max-w-4xl mx-auto">
          {depts.map((dept) => (
            <div
              key={dept.name}
              className="flex items-center gap-2.5 px-4 py-2.5 rounded-xl border border-white/[0.07] bg-white/[0.025] hover:bg-white/[0.05] hover:border-white/[0.12] transition-all cursor-default"
            >
              <dept.icon className="h-4 w-4 text-blue-400/60" />
              <span className="text-sm text-gray-300 font-medium">{dept.name}</span>
            </div>
          ))}
        </div>
        <p className="text-center text-xs text-gray-700 mt-6">
          + fully custom routing via the visual flow editor
        </p>
      </div>
    </section>
  );
}

// ─── Analytics ────────────────────────────────────────────────────────────────

function Analytics() {
  const features = [
    {
      title: "Real-Time Dashboards",
      desc: "Live call volume, resolution rates, and AI handling percentage across all channels and properties.",
    },
    {
      title: "AI Quality Scoring",
      desc: "Every call and SMS scored automatically — tone, resolution, efficiency — with zero manual effort.",
    },
    {
      title: "Custom Dispositions",
      desc: "Tag every interaction with property-specific outcomes for granular operational reporting.",
    },
    {
      title: "After-Call Work (ACW)",
      desc: "Automated post-call summaries, resolution classification, and data entry that free your team immediately.",
    },
    {
      title: "Export & Business Intelligence",
      desc: "CSV exports, scheduled reports, and integrations with your existing BI stack.",
    },
  ];

  return (
    <section className="py-32 px-6" style={{ fontFamily: "'DM Sans', sans-serif" }}>
      <div className="max-w-7xl mx-auto">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-16 items-center">
          {/* Copy */}
          <div>
            <p
              className="text-xs font-semibold tracking-[0.2em] uppercase text-blue-400 mb-4"
              style={{ fontFamily: "'Syne', sans-serif" }}
            >
              Analytics &amp; Dashboard
            </p>
            <h2
              className="text-4xl md:text-5xl font-semibold text-white mb-5"
              style={{ fontFamily: "'Cormorant Garamond', serif", lineHeight: 1.1 }}
            >
              See everything.
              <br />
              Know everything.
            </h2>
            <p className="text-gray-400 mb-10 leading-relaxed">
              Botelier captures every interaction — every word spoken, every message
              sent — and surfaces the insights your operations team needs to
              continuously improve.
            </p>

            <div className="space-y-6">
              {features.map((f) => (
                <div key={f.title} className="flex gap-3.5">
                  <div className="w-5 h-5 rounded-full bg-blue-500/15 flex items-center justify-center flex-shrink-0 mt-0.5">
                    <div className="w-1.5 h-1.5 rounded-full bg-blue-400" />
                  </div>
                  <div>
                    <div
                      className="text-sm font-semibold text-white mb-0.5"
                      style={{ fontFamily: "'Syne', sans-serif" }}
                    >
                      {f.title}
                    </div>
                    <div className="text-sm text-gray-500">{f.desc}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Dashboard mockup */}
          <div className="relative">
            <div className="rounded-2xl border border-white/[0.08] bg-[#0c0c10] overflow-hidden shadow-2xl">
              {/* Window chrome */}
              <div className="flex items-center gap-2 px-4 py-3 border-b border-white/[0.05]">
                <div className="w-2.5 h-2.5 rounded-full bg-red-500/40" />
                <div className="w-2.5 h-2.5 rounded-full bg-yellow-500/40" />
                <div className="w-2.5 h-2.5 rounded-full bg-green-500/40" />
                <div className="ml-2 px-3 py-0.5 rounded bg-white/[0.04] text-[11px] text-gray-500 font-mono">
                  Analytics · Call Overview
                </div>
              </div>

              <div className="p-4">
                {/* Stat row */}
                <div className="grid grid-cols-3 gap-2 mb-3">
                  {[
                    { label: "Calls Today", value: "284", delta: "+12%", up: true },
                    { label: "AI Handled", value: "91%", delta: "+3%", up: true },
                    { label: "Avg Duration", value: "2m 14s", delta: "–8s", up: false },
                  ].map((s) => (
                    <div
                      key={s.label}
                      className="rounded-xl bg-white/[0.03] border border-white/[0.04] p-3"
                    >
                      <div
                        className="text-xl font-bold text-white"
                        style={{ fontFamily: "'Syne', sans-serif" }}
                      >
                        {s.value}
                      </div>
                      <div className="text-[11px] text-gray-500 mt-0.5">{s.label}</div>
                      <div className={`text-[11px] mt-1 ${s.up ? "text-green-400" : "text-blue-400"}`}>
                        {s.delta}
                      </div>
                    </div>
                  ))}
                </div>

                {/* Bar chart */}
                <div className="rounded-xl bg-white/[0.02] border border-white/[0.04] p-3 mb-3">
                  <div className="text-[11px] text-gray-500 mb-3">Call Volume · Last 7 Days</div>
                  <div className="flex items-end gap-1.5 h-14">
                    {[42, 68, 47, 83, 58, 91, 73].map((h, i) => (
                      <div
                        key={i}
                        className="flex-1 rounded-t"
                        style={{
                          height: `${h}%`,
                          background: `rgba(59,130,246,${0.28 + i * 0.07})`,
                        }}
                      />
                    ))}
                  </div>
                  <div className="flex justify-between mt-1.5">
                    {["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"].map((d) => (
                      <span key={d} className="text-[10px] text-gray-600">{d}</span>
                    ))}
                  </div>
                </div>

                {/* Call log rows */}
                <div className="rounded-xl bg-white/[0.02] border border-white/[0.04] overflow-hidden">
                  <div className="px-3 py-2 border-b border-white/[0.04] text-[11px] text-gray-500 font-medium">
                    Recent Calls
                  </div>
                  {[
                    { ref: "#D1843E", num: "+1 702 ··· 4892", status: "AI Handled", score: 94 },
                    { ref: "#D1843F", num: "+1 725 ··· 1107", status: "Transferred", score: 81 },
                    { ref: "#D18440", num: "+1 702 ··· 3341", status: "AI Handled", score: 97 },
                  ].map((row) => (
                    <div
                      key={row.ref}
                      className="flex items-center justify-between px-3 py-2.5 border-b border-white/[0.03] last:border-0 text-[11px]"
                    >
                      <span className="font-mono text-gray-500">{row.ref}</span>
                      <span className="text-gray-400">{row.num}</span>
                      <span
                        className={`px-2 py-0.5 rounded-full text-[10px] ${
                          row.status === "AI Handled"
                            ? "bg-green-500/10 text-green-400"
                            : "bg-blue-500/10 text-blue-400"
                        }`}
                      >
                        {row.status}
                      </span>
                      <span className="text-gray-300 font-semibold">{row.score}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Glow */}
            <div
              className="absolute -inset-6 rounded-3xl opacity-15 -z-10"
              style={{
                background: "radial-gradient(circle at 50% 50%, #3b82f6, transparent 65%)",
                filter: "blur(50px)",
              }}
            />
          </div>
        </div>
      </div>
    </section>
  );
}

// ─── Project Phases ───────────────────────────────────────────────────────────

function ProjectPhases() {
  const phases = [
    {
      num: "01",
      title: "Discovery",
      duration: "Weeks 1–2",
      desc: "We audit your current communications setup, map workflows, and identify the highest-value automation opportunities across voice, SMS, and departments.",
      items: [
        "Current state audit",
        "Use case prioritization",
        "Department & routing mapping",
        "Integration scoping",
      ],
    },
    {
      num: "02",
      title: "Configuration",
      duration: "Weeks 2–4",
      desc: "Your AI assistants are configured and tested — knowledge bases loaded, conversation flows designed, Twilio numbers provisioned, integrations wired up.",
      items: [
        "AI assistant setup",
        "Flow design & simulation",
        "Knowledge base loading",
        "Twilio number provisioning",
      ],
    },
    {
      num: "03",
      title: "Go-Live",
      duration: "Weeks 4–6",
      desc: "Controlled launch with close monitoring. We tune performance daily based on real call data, ensuring quality and handling rates hit targets before full rollout.",
      items: [
        "Soft launch & monitoring",
        "Daily performance tuning",
        "Team training & shadowing",
        "Escalation path setup",
      ],
    },
    {
      num: "04",
      title: "Optimize",
      duration: "Ongoing",
      desc: "With the foundation in place, we continuously improve through analytics review, new use case expansion, AI model updates, and regular QBRs.",
      items: [
        "Monthly QBRs",
        "AI model updates",
        "New use case expansion",
        "Multi-property rollout",
      ],
    },
  ];

  return (
    <section
      className="py-32 px-6 relative"
      style={{ fontFamily: "'DM Sans', sans-serif" }}
    >
      <div
        className="absolute inset-0 border-y border-white/[0.04] pointer-events-none"
        style={{
          background:
            "linear-gradient(to bottom, transparent, rgba(59,130,246,0.018), transparent)",
        }}
      />
      <div className="relative max-w-7xl mx-auto">
        <div className="text-center mb-16">
          <p
            className="text-xs font-semibold tracking-[0.2em] uppercase text-blue-400 mb-4"
            style={{ fontFamily: "'Syne', sans-serif" }}
          >
            Implementation
          </p>
          <h2
            className="text-4xl md:text-5xl font-semibold text-white mb-4"
            style={{ fontFamily: "'Cormorant Garamond', serif", lineHeight: 1.1 }}
          >
            From signed to live
            <br />
            in weeks, not months
          </h2>
          <p className="text-gray-400 max-w-xl mx-auto">
            A proven implementation framework that gets you to value quickly while
            building a foundation for long-term AI maturity.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {phases.map((phase) => (
            <div
              key={phase.num}
              className="rounded-2xl border border-white/[0.06] bg-white/[0.02] p-6 hover:border-white/[0.10] hover:bg-white/[0.03] transition-all"
            >
              <div className="flex items-start justify-between mb-5">
                <span
                  className="text-4xl font-bold text-white/[0.07] select-none"
                  style={{ fontFamily: "'Syne', sans-serif" }}
                >
                  {phase.num}
                </span>
                <span
                  className="text-xs text-blue-400 border border-blue-500/20 bg-blue-500/10 px-2.5 py-0.5 rounded-full"
                  style={{ fontFamily: "'Syne', sans-serif" }}
                >
                  {phase.duration}
                </span>
              </div>
              <h3
                className="text-base font-semibold text-white mb-2"
                style={{ fontFamily: "'Syne', sans-serif" }}
              >
                {phase.title}
              </h3>
              <p className="text-sm text-gray-500 leading-relaxed mb-5">{phase.desc}</p>
              <ul className="space-y-2">
                {phase.items.map((item) => (
                  <li key={item} className="flex items-center gap-2 text-xs text-gray-500">
                    <div className="w-1 h-1 rounded-full bg-blue-400/50 flex-shrink-0" />
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ─── CTA Banner ───────────────────────────────────────────────────────────────

function CTABanner() {
  return (
    <section className="py-32 px-6" style={{ fontFamily: "'DM Sans', sans-serif" }}>
      <div className="max-w-4xl mx-auto text-center relative">
        <div
          className="absolute inset-0 rounded-3xl pointer-events-none"
          style={{
            background:
              "radial-gradient(ellipse at center, rgba(59,130,246,0.10) 0%, transparent 70%)",
          }}
        />
        <div className="relative">
          <p
            className="text-xs font-semibold tracking-[0.2em] uppercase text-blue-400 mb-6"
            style={{ fontFamily: "'Syne', sans-serif" }}
          >
            Get Started
          </p>
          <h2
            className="text-4xl md:text-6xl font-semibold text-white mb-6"
            style={{ fontFamily: "'Cormorant Garamond', serif", lineHeight: 1.08 }}
          >
            Ready to transform
            <br />
            guest communications?
          </h2>
          <p className="text-gray-400 mb-10 text-lg max-w-xl mx-auto leading-relaxed">
            Join forward-thinking hospitality brands using Botelier to automate,
            analyze, and elevate every guest interaction.
          </p>
          <a
            href="mailto:sales@botelier.ai"
            className="inline-flex items-center gap-2 px-8 py-4 bg-blue-600 hover:bg-blue-500 text-white rounded-xl font-medium text-base transition-all hover:scale-[1.03] shadow-xl shadow-blue-900/40"
          >
            Contact Sales
            <ArrowRight className="h-5 w-5" />
          </a>
        </div>
      </div>
    </section>
  );
}

// ─── Footer ───────────────────────────────────────────────────────────────────

function Footer() {
  return (
    <footer
      className="border-t border-white/[0.05] py-10 px-6"
      style={{ fontFamily: "'DM Sans', sans-serif" }}
    >
      <div className="max-w-7xl mx-auto flex flex-col md:flex-row items-center justify-between gap-6">
        <div className="flex items-center gap-3">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center">
            <span
              className="text-xs font-bold text-white"
              style={{ fontFamily: "'Syne', sans-serif" }}
            >
              B
            </span>
          </div>
          <span
            className="text-white font-semibold text-sm"
            style={{ fontFamily: "'Syne', sans-serif" }}
          >
            Botelier
          </span>
          <span className="text-gray-700 text-sm hidden md:inline">
            · AI Communications Platform
          </span>
        </div>
        <div className="flex items-center gap-6 text-sm text-gray-500">
          <a href="/login" className="hover:text-gray-300 transition-colors">
            Log In
          </a>
          <a
            href="mailto:sales@botelier.ai"
            className="hover:text-gray-300 transition-colors"
          >
            Contact Sales
          </a>
          <span className="text-gray-700">
            © {new Date().getFullYear()} Botelier
          </span>
        </div>
      </div>
    </footer>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function HomePage() {
  const router = useRouter();
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    // Redirect logged-in users to their home without showing the marketing page
    try {
      const token = localStorage.getItem("botelier_token");
      const userStr = localStorage.getItem("botelier_user");
      if (token && userStr) {
        const user = JSON.parse(userStr);
        router.replace(
          user?.user_type === "platform_admin" ? "/admin" : "/dashboard/assistants"
        );
        return;
      }
    } catch {
      // stay on marketing page
    }

    const onScroll = () => setScrolled(window.scrollY > 24);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [router]);

  return (
    <div className="min-h-screen bg-[#050507] text-white antialiased">
        <Nav scrolled={scrolled} />
        <Hero />
        <GuestJourney />
        <UseCases />
        <Departments />
        <Analytics />
        <ProjectPhases />
        <CTABanner />
        <Footer />
    </div>
  );
}
