import {
  Phone,
  PhoneOff,
  PhoneMissed,
  PhoneForwarded,
} from "lucide-react";

export function formatDuration(seconds: number): string {
  if (!seconds || seconds < 0) return "0:00";
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

export function formatPhoneNumber(phone: string | null): string {
  if (!phone) return "Unknown";
  if (phone.length > 6) {
    return phone.slice(0, 3) + " •••• ••" + phone.slice(-2);
  }
  return phone;
}

export function getStatusIcon(status: string) {
  switch (status) {
    case "completed":
      return <Phone className="h-4 w-4 text-green-400" />;
    case "ended_early":
      return <PhoneOff className="h-4 w-4 text-orange-400" />;
    case "failed":
      return <PhoneOff className="h-4 w-4 text-red-400" />;
    case "no_answer":
    case "busy":
      return <PhoneMissed className="h-4 w-4 text-yellow-400" />;
    case "transferred":
      return <PhoneForwarded className="h-4 w-4 text-blue-400" />;
    default:
      return <Phone className="h-4 w-4 text-gray-400" />;
  }
}

export function getStatusBadge(status: string) {
  const styles: Record<string, string> = {
    completed: "bg-green-500/10 text-green-400 border-green-500/20",
    ended_early: "bg-orange-500/10 text-orange-400 border-orange-500/20",
    failed: "bg-red-500/10 text-red-400 border-red-500/20",
    no_answer: "bg-yellow-500/10 text-yellow-400 border-yellow-500/20",
    busy: "bg-yellow-500/10 text-yellow-400 border-yellow-500/20",
    in_progress: "bg-blue-500/10 text-blue-400 border-blue-500/20",
    ringing: "bg-cyan-500/10 text-cyan-400 border-cyan-500/20",
    initiated: "bg-gray-500/10 text-gray-400 border-gray-500/20",
    transferred: "bg-purple-500/10 text-purple-400 border-purple-500/20",
    canceled: "bg-orange-500/10 text-orange-400 border-orange-500/20",
  };
  return styles[status] || "bg-gray-500/10 text-gray-400 border-gray-500/20";
}

export function getLegTypeLabel(legType: string): string {
  switch (legType) {
    case "ai_conversation":
      return "AI Assistant";
    case "transfer_external":
      return "Warm Transfer";
    case "transfer_sip":
      return "SIP Transfer";
    case "transfer_internal":
      return "Internal Transfer";
    case "transfer_cold":
      return "Cold Transfer (SIP REFER)";
    default:
      return legType;
  }
}
