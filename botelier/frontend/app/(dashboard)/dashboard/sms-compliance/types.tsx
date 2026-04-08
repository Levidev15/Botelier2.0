import { Check, AlertCircle, Clock } from "lucide-react";

export interface Brand {
  id: string;
  account_id: string;
  brand_type: string;
  business_name: string;
  business_type: string | null;
  business_industry: string | null;
  ein: string | null;
  ein_issuing_country: string;
  company_type: string | null;
  stock_symbol: string | null;
  stock_exchange: string | null;
  website_url: string | null;
  street: string | null;
  city: string | null;
  region: string | null;
  postal_code: string | null;
  country: string;
  rep_first_name: string | null;
  rep_last_name: string | null;
  rep_email: string | null;
  rep_phone: string | null;
  rep_title: string | null;
  rep_job_position: string | null;
  twilio_customer_profile_sid: string | null;
  twilio_a2p_profile_sid: string | null;
  twilio_brand_sid: string | null;
  status: string;
  failure_reason: string | null;
  trust_score: string | null;
  twilio_status_raw: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface Campaign {
  id: string;
  brand_id: string;
  account_id: string;
  friendly_name: string;
  use_case: string;
  description: string | null;
  message_samples: string[];
  message_flow: string | null;
  has_embedded_links: boolean;
  has_embedded_phone: boolean;
  opt_in_message: string | null;
  opt_in_keywords: string | null;
  opt_out_message: string | null;
  opt_out_keywords: string | null;
  help_message: string | null;
  help_keywords: string | null;
  twilio_messaging_service_sid: string | null;
  twilio_campaign_sid: string | null;
  assigned_phone_numbers: string[];
  status: string;
  failure_reason: string | null;
  twilio_status_raw: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface PhoneNumberOption {
  id: string;
  twilio_sid: string;
  phone_number: string;
  friendly_name: string;
}

export const BUSINESS_TYPES = ["Corporation", "LLC", "Partnership", "Sole Proprietorship", "Non-Profit"];
export const BUSINESS_INDUSTRIES = ["Technology", "Hospitality", "Healthcare", "Finance", "Education", "Retail", "Real Estate", "Other"];
export const COMPANY_TYPES = [
  { value: "private_profit", label: "Private (For Profit)" },
  { value: "public_profit", label: "Public (For Profit)" },
  { value: "non_profit", label: "Non-Profit" },
  { value: "government", label: "Government" },
];
export const BRAND_TYPES = [
  { value: "standard", label: "Standard" },
  { value: "low_volume", label: "Low Volume" },
  { value: "starter", label: "Starter" },
  { value: "sole_proprietor", label: "Sole Proprietor" },
];
export const USE_CASES = [
  "2FA", "ACCOUNT_NOTIFICATION", "CUSTOMER_CARE", "DELIVERY_NOTIFICATION",
  "FRAUD_ALERT", "HIGHER_EDUCATION", "MARKETING", "POLLING_VOTING",
  "PUBLIC_SERVICE_ANNOUNCEMENT", "SECURITY_ALERT", "MIXED", "LOW_VOLUME",
];

export const defaultBrandForm = {
  business_name: "",
  business_type: "",
  business_industry: "",
  ein: "",
  ein_issuing_country: "US",
  company_type: "",
  website_url: "",
  street: "",
  city: "",
  region: "",
  postal_code: "",
  country: "US",
  rep_first_name: "",
  rep_last_name: "",
  rep_email: "",
  rep_phone: "",
  rep_title: "",
  rep_job_position: "",
  brand_type: "standard",
};

export const defaultCampaignForm = {
  friendly_name: "",
  use_case: "CUSTOMER_CARE",
  description: "",
  message_samples: [""],
  message_flow: "",
  has_embedded_links: false,
  has_embedded_phone: false,
  opt_in_message: "",
  opt_in_keywords: "YES,START",
  opt_out_message: "",
  opt_out_keywords: "STOP,END,CANCEL,UNSUBSCRIBE,QUIT",
  help_message: "",
  help_keywords: "HELP,INFO",
};

export function getStatusBadge(status: string) {
  const map: Record<string, string> = {
    draft: "bg-gray-500/20 text-gray-400",
    pending: "bg-yellow-500/20 text-yellow-400",
    in_review: "bg-blue-500/20 text-blue-400",
    approved: "bg-green-500/20 text-green-400",
    failed: "bg-red-500/20 text-red-400",
    suspended: "bg-red-500/20 text-red-400",
  };
  return map[status] || "bg-gray-500/20 text-gray-400";
}

export function StatusIcon({ status }: { status: string }) {
  switch (status) {
    case "approved": return <Check className="h-3.5 w-3.5" />;
    case "failed":
    case "suspended": return <AlertCircle className="h-3.5 w-3.5" />;
    case "pending":
    case "in_review": return <Clock className="h-3.5 w-3.5" />;
    default: return null;
  }
}
