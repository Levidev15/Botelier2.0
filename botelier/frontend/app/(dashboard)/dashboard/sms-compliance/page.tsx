"use client";

import { useState, useEffect } from "react";
import {
  Shield, Plus, RefreshCw, Trash2, Edit3, Phone, Check,
  AlertCircle, Clock, Send, ChevronDown, ChevronUp, X,
} from "lucide-react";
import { useAccountContext } from "@/lib/auth/useAccountContext";
import { toast } from "sonner";

interface Brand {
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

interface Campaign {
  id: string;
  brand_id: string;
  hotel_id: string;
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

interface PhoneNumberOption {
  id: string;
  twilio_sid: string;
  phone_number: string;
  friendly_name: string;
}

const BUSINESS_TYPES = ["Corporation", "LLC", "Partnership", "Sole Proprietorship", "Non-Profit"];
const BUSINESS_INDUSTRIES = ["Technology", "Hospitality", "Healthcare", "Finance", "Education", "Retail", "Real Estate", "Other"];
const COMPANY_TYPES = [
  { value: "private_profit", label: "Private (For Profit)" },
  { value: "public_profit", label: "Public (For Profit)" },
  { value: "non_profit", label: "Non-Profit" },
  { value: "government", label: "Government" },
];
const BRAND_TYPES = [
  { value: "standard", label: "Standard" },
  { value: "low_volume", label: "Low Volume" },
  { value: "starter", label: "Starter" },
  { value: "sole_proprietor", label: "Sole Proprietor" },
];
const USE_CASES = [
  "2FA", "ACCOUNT_NOTIFICATION", "CUSTOMER_CARE", "DELIVERY_NOTIFICATION",
  "FRAUD_ALERT", "HIGHER_EDUCATION", "MARKETING", "POLLING_VOTING",
  "PUBLIC_SERVICE_ANNOUNCEMENT", "SECURITY_ALERT", "MIXED", "LOW_VOLUME",
];

function getStatusBadge(status: string) {
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

function StatusIcon({ status }: { status: string }) {
  switch (status) {
    case "approved": return <Check className="h-3.5 w-3.5" />;
    case "failed":
    case "suspended": return <AlertCircle className="h-3.5 w-3.5" />;
    case "pending":
    case "in_review": return <Clock className="h-3.5 w-3.5" />;
    default: return null;
  }
}

const defaultBrandForm = {
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

const defaultCampaignForm = {
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

export default function SMSCompliancePage() {
  const { accountId, loading: contextLoading } = useAccountContext();

  const [brands, setBrands] = useState<Brand[]>([]);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [phoneNumbers, setPhoneNumbers] = useState<PhoneNumberOption[]>([]);
  const [loading, setLoading] = useState(true);

  const [showBrandForm, setShowBrandForm] = useState(false);
  const [editingBrand, setEditingBrand] = useState<Brand | null>(null);
  const [brandForm, setBrandForm] = useState({ ...defaultBrandForm });
  const [brandSubmitting, setBrandSubmitting] = useState(false);

  const [showCampaignForm, setShowCampaignForm] = useState(false);
  const [editingCampaign, setEditingCampaign] = useState<Campaign | null>(null);
  const [campaignForm, setCampaignForm] = useState({ ...defaultCampaignForm });
  const [campaignSubmitting, setCampaignSubmitting] = useState(false);

  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [selectedPhoneNumber, setSelectedPhoneNumber] = useState<Record<string, string>>({});

  const brand = brands.length > 0 ? brands[0] : null;

  const fetchBrands = async () => {
    if (!accountId) return;
    try {
      const res = await fetch(`/api/sms-compliance/brands?account_id=${accountId}`);
      if (res.ok) {
        const data = await res.json();
        setBrands(data);
      }
    } catch (error) {
      console.error("Failed to fetch brands:", error);
    }
  };

  const fetchCampaigns = async () => {
    if (!accountId) return;
    try {
      const res = await fetch(`/api/sms-compliance/campaigns?hotel_id=${accountId}`);
      if (res.ok) {
        const data = await res.json();
        setCampaigns(data);
      }
    } catch (error) {
      console.error("Failed to fetch campaigns:", error);
    }
  };

  const fetchPhoneNumbers = async () => {
    if (!accountId) return;
    try {
      const res = await fetch(`/api/sms-compliance/hotels/${accountId}/phone-numbers`);
      if (res.ok) {
        const data = await res.json();
        setPhoneNumbers(data);
      }
    } catch (error) {
      console.error("Failed to fetch phone numbers:", error);
    }
  };

  const loadAll = async () => {
    setLoading(true);
    await Promise.all([fetchBrands(), fetchCampaigns(), fetchPhoneNumbers()]);
    setLoading(false);
  };

  useEffect(() => {
    if (!contextLoading && accountId) {
      loadAll();
    }
  }, [accountId, contextLoading]);

  const openBrandCreate = () => {
    setEditingBrand(null);
    setBrandForm({ ...defaultBrandForm });
    setShowBrandForm(true);
  };

  const openBrandEdit = (b: Brand) => {
    setEditingBrand(b);
    setBrandForm({
      business_name: b.business_name || "",
      business_type: b.business_type || "",
      business_industry: b.business_industry || "",
      ein: b.ein || "",
      ein_issuing_country: b.ein_issuing_country || "US",
      company_type: b.company_type || "",
      website_url: b.website_url || "",
      street: b.street || "",
      city: b.city || "",
      region: b.region || "",
      postal_code: b.postal_code || "",
      country: b.country || "US",
      rep_first_name: b.rep_first_name || "",
      rep_last_name: b.rep_last_name || "",
      rep_email: b.rep_email || "",
      rep_phone: b.rep_phone || "",
      rep_title: b.rep_title || "",
      rep_job_position: b.rep_job_position || "",
      brand_type: b.brand_type || "standard",
    });
    setShowBrandForm(true);
  };

  const handleBrandSubmit = async () => {
    if (!accountId) return;
    setBrandSubmitting(true);
    try {
      const url = editingBrand
        ? `/api/sms-compliance/brands/${editingBrand.id}`
        : `/api/sms-compliance/brands`;
      const method = editingBrand ? "PUT" : "POST";
      const body = editingBrand
        ? { ...brandForm }
        : { ...brandForm, account_id: accountId };

      const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (res.ok) {
        toast.success(editingBrand ? "Brand updated" : "Brand created");
        setShowBrandForm(false);
        await fetchBrands();
      } else {
        const err = await res.json();
        toast.error(err.detail || "Failed to save brand");
      }
    } catch (error) {
      toast.error("Failed to save brand");
    } finally {
      setBrandSubmitting(false);
    }
  };

  const handleBrandAction = async (action: string, brandId: string) => {
    setActionLoading(`brand-${action}-${brandId}`);
    try {
      let res: Response;
      if (action === "submit") {
        res = await fetch(`/api/sms-compliance/brands/${brandId}/submit`, { method: "POST" });
      } else if (action === "refresh") {
        res = await fetch(`/api/sms-compliance/brands/${brandId}/refresh`, { method: "POST" });
      } else if (action === "delete") {
        res = await fetch(`/api/sms-compliance/brands/${brandId}`, { method: "DELETE" });
      } else return;

      if (res.ok) {
        toast.success(
          action === "submit" ? "Brand submitted to Twilio" :
          action === "refresh" ? "Brand status refreshed" :
          "Brand deleted"
        );
        await loadAll();
      } else {
        const err = await res.json();
        toast.error(err.detail || `Failed to ${action} brand`);
      }
    } catch (error) {
      toast.error(`Failed to ${action} brand`);
    } finally {
      setActionLoading(null);
    }
  };

  const openCampaignCreate = () => {
    setEditingCampaign(null);
    setCampaignForm({ ...defaultCampaignForm });
    setShowCampaignForm(true);
  };

  const openCampaignEdit = (c: Campaign) => {
    setEditingCampaign(c);
    setCampaignForm({
      friendly_name: c.friendly_name || "",
      use_case: c.use_case || "CUSTOMER_CARE",
      description: c.description || "",
      message_samples: c.message_samples?.length > 0 ? [...c.message_samples] : [""],
      message_flow: c.message_flow || "",
      has_embedded_links: c.has_embedded_links || false,
      has_embedded_phone: c.has_embedded_phone || false,
      opt_in_message: c.opt_in_message || "",
      opt_in_keywords: c.opt_in_keywords || "YES,START",
      opt_out_message: c.opt_out_message || "",
      opt_out_keywords: c.opt_out_keywords || "STOP,END,CANCEL,UNSUBSCRIBE,QUIT",
      help_message: c.help_message || "",
      help_keywords: c.help_keywords || "HELP,INFO",
    });
    setShowCampaignForm(true);
  };

  const handleCampaignSubmit = async () => {
    if (!accountId || !brand) return;
    setCampaignSubmitting(true);
    try {
      const url = editingCampaign
        ? `/api/sms-compliance/campaigns/${editingCampaign.id}`
        : `/api/sms-compliance/campaigns`;
      const method = editingCampaign ? "PUT" : "POST";
      const samples = campaignForm.message_samples.filter((s) => s.trim() !== "");
      const body = editingCampaign
        ? { ...campaignForm, message_samples: samples }
        : { ...campaignForm, message_samples: samples, brand_id: brand.id, hotel_id: accountId };

      const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (res.ok) {
        toast.success(editingCampaign ? "Campaign updated" : "Campaign created");
        setShowCampaignForm(false);
        await fetchCampaigns();
      } else {
        const err = await res.json();
        toast.error(err.detail || "Failed to save campaign");
      }
    } catch (error) {
      toast.error("Failed to save campaign");
    } finally {
      setCampaignSubmitting(false);
    }
  };

  const handleCampaignAction = async (action: string, campaignId: string) => {
    setActionLoading(`campaign-${action}-${campaignId}`);
    try {
      let res: Response;
      if (action === "submit") {
        res = await fetch(`/api/sms-compliance/campaigns/${campaignId}/submit`, { method: "POST" });
      } else if (action === "refresh") {
        res = await fetch(`/api/sms-compliance/campaigns/${campaignId}/refresh`, { method: "POST" });
      } else if (action === "delete") {
        res = await fetch(`/api/sms-compliance/campaigns/${campaignId}`, { method: "DELETE" });
      } else return;

      if (res.ok) {
        toast.success(
          action === "submit" ? "Campaign submitted to Twilio" :
          action === "refresh" ? "Campaign status refreshed" :
          "Campaign deleted"
        );
        await fetchCampaigns();
      } else {
        const err = await res.json();
        toast.error(err.detail || `Failed to ${action} campaign`);
      }
    } catch (error) {
      toast.error(`Failed to ${action} campaign`);
    } finally {
      setActionLoading(null);
    }
  };

  const handleAssignPhone = async (campaignId: string) => {
    const sid = selectedPhoneNumber[campaignId];
    if (!sid) return;
    setActionLoading(`assign-${campaignId}`);
    try {
      const res = await fetch(`/api/sms-compliance/campaigns/${campaignId}/phone-numbers`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone_number_sid: sid }),
      });
      if (res.ok) {
        toast.success("Phone number assigned");
        setSelectedPhoneNumber((prev) => ({ ...prev, [campaignId]: "" }));
        await fetchCampaigns();
      } else {
        const err = await res.json();
        toast.error(err.detail || "Failed to assign phone number");
      }
    } catch (error) {
      toast.error("Failed to assign phone number");
    } finally {
      setActionLoading(null);
    }
  };

  const handleRemovePhone = async (campaignId: string, phoneSid: string) => {
    setActionLoading(`remove-${campaignId}-${phoneSid}`);
    try {
      const res = await fetch(
        `/api/sms-compliance/campaigns/${campaignId}/phone-numbers/${phoneSid}`,
        { method: "DELETE" }
      );
      if (res.ok) {
        toast.success("Phone number removed");
        await fetchCampaigns();
      } else {
        const err = await res.json();
        toast.error(err.detail || "Failed to remove phone number");
      }
    } catch (error) {
      toast.error("Failed to remove phone number");
    } finally {
      setActionLoading(null);
    }
  };

  const addMessageSample = () => {
    setCampaignForm((prev) => ({
      ...prev,
      message_samples: [...prev.message_samples, ""],
    }));
  };

  const removeMessageSample = (idx: number) => {
    setCampaignForm((prev) => ({
      ...prev,
      message_samples: prev.message_samples.filter((_, i) => i !== idx),
    }));
  };

  const updateMessageSample = (idx: number, value: string) => {
    setCampaignForm((prev) => ({
      ...prev,
      message_samples: prev.message_samples.map((s, i) => (i === idx ? value : s)),
    }));
  };

  if (contextLoading || loading) {
    return (
      <div className="flex items-center justify-center h-full bg-[#0a0a0a]">
        <div className="flex flex-col items-center gap-3">
          <RefreshCw className="h-8 w-8 text-blue-500 animate-spin" />
          <p className="text-gray-400 text-sm">Loading SMS Compliance...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-full bg-[#0a0a0a] p-6">
      <div className="max-w-5xl mx-auto space-y-8">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <Shield className="h-7 w-7 text-blue-500" />
            <h1 className="text-2xl font-bold text-white">SMS Compliance</h1>
          </div>
          <p className="text-gray-400 text-sm ml-10">
            Manage A2P 10DLC registration for SMS messaging
          </p>
        </div>

        <section>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold text-white">Brand Registration</h2>
            {!brand && (
              <button
                onClick={openBrandCreate}
                className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium transition-colors"
              >
                <Plus className="h-4 w-4" />
                Register Brand
              </button>
            )}
          </div>

          {brand ? (
            <div className="bg-[#141414] border border-gray-800 rounded-xl p-6 space-y-4">
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-3 mb-1">
                    <h3 className="text-xl font-semibold text-white">{brand.business_name}</h3>
                    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${getStatusBadge(brand.status)}`}>
                      <StatusIcon status={brand.status} />
                      {brand.status.replace("_", " ")}
                    </span>
                  </div>
                  <p className="text-sm text-gray-400">
                    {brand.brand_type?.replace("_", " ")} brand
                    {brand.ein && ` · EIN: ${brand.ein}`}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  {(brand.status === "draft" || brand.status === "failed") && (
                    <>
                      <button
                        onClick={() => openBrandEdit(brand)}
                        className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-700 hover:bg-gray-600 text-gray-200 rounded-lg text-xs transition-colors"
                      >
                        <Edit3 className="h-3.5 w-3.5" />
                        Edit
                      </button>
                      <button
                        onClick={() => handleBrandAction("submit", brand.id)}
                        disabled={actionLoading === `brand-submit-${brand.id}`}
                        className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-xs transition-colors disabled:opacity-50"
                      >
                        <Send className="h-3.5 w-3.5" />
                        {actionLoading === `brand-submit-${brand.id}` ? "Submitting..." : "Submit to Twilio"}
                      </button>
                      <button
                        onClick={() => handleBrandAction("delete", brand.id)}
                        disabled={actionLoading === `brand-delete-${brand.id}`}
                        className="flex items-center gap-1.5 px-3 py-1.5 bg-red-600/20 hover:bg-red-600/30 text-red-400 rounded-lg text-xs transition-colors disabled:opacity-50"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                        {actionLoading === `brand-delete-${brand.id}` ? "Deleting..." : "Delete"}
                      </button>
                    </>
                  )}
                  {(brand.status === "pending" || brand.status === "in_review") && (
                    <button
                      onClick={() => handleBrandAction("refresh", brand.id)}
                      disabled={actionLoading === `brand-refresh-${brand.id}`}
                      className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-700 hover:bg-gray-600 text-gray-200 rounded-lg text-xs transition-colors disabled:opacity-50"
                    >
                      <RefreshCw className={`h-3.5 w-3.5 ${actionLoading === `brand-refresh-${brand.id}` ? "animate-spin" : ""}`} />
                      Refresh Status
                    </button>
                  )}
                </div>
              </div>

              {brand.failure_reason && (
                <div className="flex items-start gap-2 p-3 bg-red-500/10 border border-red-500/20 rounded-lg">
                  <AlertCircle className="h-4 w-4 text-red-400 mt-0.5 flex-shrink-0" />
                  <p className="text-sm text-red-300">{brand.failure_reason}</p>
                </div>
              )}

              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <p className="text-gray-500 text-xs mb-1">Address</p>
                  <p className="text-gray-300">
                    {[brand.street, brand.city, brand.region, brand.postal_code, brand.country]
                      .filter(Boolean)
                      .join(", ") || "—"}
                  </p>
                </div>
                <div>
                  <p className="text-gray-500 text-xs mb-1">Authorized Representative</p>
                  <p className="text-gray-300">
                    {[brand.rep_first_name, brand.rep_last_name].filter(Boolean).join(" ") || "—"}
                    {brand.rep_title && ` (${brand.rep_title})`}
                  </p>
                </div>
                {brand.trust_score && (
                  <div>
                    <p className="text-gray-500 text-xs mb-1">Trust Score</p>
                    <p className="text-gray-300">{brand.trust_score}</p>
                  </div>
                )}
                {brand.website_url && (
                  <div>
                    <p className="text-gray-500 text-xs mb-1">Website</p>
                    <p className="text-gray-300">{brand.website_url}</p>
                  </div>
                )}
              </div>

              {(brand.twilio_customer_profile_sid || brand.twilio_brand_sid || brand.twilio_a2p_profile_sid) && (
                <div className="pt-3 border-t border-gray-800">
                  <p className="text-gray-500 text-xs mb-2">Twilio SIDs</p>
                  <div className="flex flex-wrap gap-2 text-xs">
                    {brand.twilio_customer_profile_sid && (
                      <span className="px-2 py-1 bg-[#1a1a1a] border border-gray-700 rounded text-gray-400">
                        Profile: {brand.twilio_customer_profile_sid}
                      </span>
                    )}
                    {brand.twilio_brand_sid && (
                      <span className="px-2 py-1 bg-[#1a1a1a] border border-gray-700 rounded text-gray-400">
                        Brand: {brand.twilio_brand_sid}
                      </span>
                    )}
                    {brand.twilio_a2p_profile_sid && (
                      <span className="px-2 py-1 bg-[#1a1a1a] border border-gray-700 rounded text-gray-400">
                        A2P: {brand.twilio_a2p_profile_sid}
                      </span>
                    )}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="bg-[#141414] border border-gray-800 rounded-xl p-12 flex flex-col items-center text-center">
              <Shield className="h-12 w-12 text-gray-600 mb-4" />
              <h3 className="text-lg font-medium text-gray-300 mb-2">No Brand Registered</h3>
              <p className="text-gray-500 text-sm max-w-md mb-6">
                Register your business brand to comply with A2P 10DLC regulations and enable SMS messaging capabilities.
              </p>
              <button
                onClick={openBrandCreate}
                className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium transition-colors"
              >
                <Plus className="h-4 w-4" />
                Register Brand
              </button>
            </div>
          )}
        </section>

        {brand && (
          <section>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold text-white">Campaigns</h2>
              {brand.status === "approved" && (
                <button
                  onClick={openCampaignCreate}
                  className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium transition-colors"
                >
                  <Plus className="h-4 w-4" />
                  Add Campaign
                </button>
              )}
            </div>

            {brand.status !== "approved" ? (
              <div className="bg-[#141414] border border-gray-800 rounded-xl p-12 flex flex-col items-center text-center">
                {(brand.status === "pending" || brand.status === "in_review") && (
                  <>
                    <Clock className="h-10 w-10 text-yellow-500 mb-3" />
                    <p className="text-gray-300 text-sm font-medium">Brand Under Review</p>
                    <p className="text-gray-500 text-xs mt-1 max-w-md">
                      Your brand registration is being reviewed. Once approved, you'll be able to create campaigns and start sending compliant SMS messages.
                    </p>
                  </>
                )}
                {brand.status === "failed" && (
                  <>
                    <AlertCircle className="h-10 w-10 text-red-500 mb-3" />
                    <p className="text-gray-300 text-sm font-medium">Brand Registration Failed</p>
                    <p className="text-gray-500 text-xs mt-1 max-w-md">
                      Your brand registration was not approved. Please edit your brand details and resubmit before creating campaigns.
                    </p>
                  </>
                )}
                {brand.status === "draft" && (
                  <>
                    <Shield className="h-10 w-10 text-gray-600 mb-3" />
                    <p className="text-gray-300 text-sm font-medium">Brand Not Submitted</p>
                    <p className="text-gray-500 text-xs mt-1 max-w-md">
                      Submit your brand registration for review first. Once approved, you'll be able to create campaigns.
                    </p>
                  </>
                )}
                {brand.status === "suspended" && (
                  <>
                    <AlertCircle className="h-10 w-10 text-orange-500 mb-3" />
                    <p className="text-gray-300 text-sm font-medium">Brand Suspended</p>
                    <p className="text-gray-500 text-xs mt-1 max-w-md">
                      Your brand has been suspended. Campaign creation is unavailable until the suspension is resolved. Please contact support for assistance.
                    </p>
                  </>
                )}
              </div>
            ) : campaigns.length === 0 ? (
              <div className="bg-[#141414] border border-gray-800 rounded-xl p-12 flex flex-col items-center text-center">
                <Send className="h-10 w-10 text-gray-600 mb-3" />
                <p className="text-gray-400 text-sm">No campaigns yet</p>
                <p className="text-gray-500 text-xs mt-1">Create a campaign to start sending compliant SMS messages</p>
              </div>
            ) : (
              <div className="space-y-4">
                {campaigns.map((c) => (
                  <CampaignCard
                    key={c.id}
                    campaign={c}
                    phoneNumbers={phoneNumbers}
                    actionLoading={actionLoading}
                    selectedPhoneNumber={selectedPhoneNumber}
                    onEdit={() => openCampaignEdit(c)}
                    onAction={(action) => handleCampaignAction(action, c.id)}
                    onAssignPhone={() => handleAssignPhone(c.id)}
                    onRemovePhone={(sid) => handleRemovePhone(c.id, sid)}
                    onSelectPhone={(sid) =>
                      setSelectedPhoneNumber((prev) => ({ ...prev, [c.id]: sid }))
                    }
                  />
                ))}
              </div>
            )}
          </section>
        )}
      </div>

      {showBrandForm && (
        <Modal title={editingBrand ? "Edit Brand" : "Register Brand"} onClose={() => setShowBrandForm(false)}>
          <div className="space-y-6 max-h-[70vh] overflow-y-auto pr-2">
            <FormSection title="Brand Type">
              <div className="flex flex-wrap gap-3">
                {BRAND_TYPES.map((bt) => (
                  <label key={bt.value} className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="radio"
                      name="brand_type"
                      value={bt.value}
                      checked={brandForm.brand_type === bt.value}
                      onChange={(e) => setBrandForm((f) => ({ ...f, brand_type: e.target.value }))}
                      className="accent-blue-600"
                    />
                    <span className="text-sm text-gray-300">{bt.label}</span>
                  </label>
                ))}
              </div>
            </FormSection>

            <FormSection title="Business Information">
              <div className="grid grid-cols-2 gap-3">
                <Input label="Business Name *" value={brandForm.business_name} onChange={(v) => setBrandForm((f) => ({ ...f, business_name: v }))} />
                <Select label="Business Type" value={brandForm.business_type} options={BUSINESS_TYPES} onChange={(v) => setBrandForm((f) => ({ ...f, business_type: v }))} />
                <Select label="Business Industry" value={brandForm.business_industry} options={BUSINESS_INDUSTRIES} onChange={(v) => setBrandForm((f) => ({ ...f, business_industry: v }))} />
                <Input label="EIN" value={brandForm.ein} onChange={(v) => setBrandForm((f) => ({ ...f, ein: v }))} />
                <Input label="EIN Issuing Country" value={brandForm.ein_issuing_country} onChange={(v) => setBrandForm((f) => ({ ...f, ein_issuing_country: v }))} />
                <Select label="Company Type" value={brandForm.company_type} options={COMPANY_TYPES.map((ct) => ct.value)} labels={COMPANY_TYPES.map((ct) => ct.label)} onChange={(v) => setBrandForm((f) => ({ ...f, company_type: v }))} />
                <Input label="Website URL" value={brandForm.website_url} onChange={(v) => setBrandForm((f) => ({ ...f, website_url: v }))} className="col-span-2" />
              </div>
            </FormSection>

            <FormSection title="Address">
              <div className="grid grid-cols-2 gap-3">
                <Input label="Street" value={brandForm.street} onChange={(v) => setBrandForm((f) => ({ ...f, street: v }))} className="col-span-2" />
                <Input label="City" value={brandForm.city} onChange={(v) => setBrandForm((f) => ({ ...f, city: v }))} />
                <Input label="State/Region" value={brandForm.region} onChange={(v) => setBrandForm((f) => ({ ...f, region: v }))} />
                <Input label="Postal Code" value={brandForm.postal_code} onChange={(v) => setBrandForm((f) => ({ ...f, postal_code: v }))} />
                <Input label="Country" value={brandForm.country} onChange={(v) => setBrandForm((f) => ({ ...f, country: v }))} />
              </div>
            </FormSection>

            <FormSection title="Authorized Representative">
              <div className="grid grid-cols-2 gap-3">
                <Input label="First Name" value={brandForm.rep_first_name} onChange={(v) => setBrandForm((f) => ({ ...f, rep_first_name: v }))} />
                <Input label="Last Name" value={brandForm.rep_last_name} onChange={(v) => setBrandForm((f) => ({ ...f, rep_last_name: v }))} />
                <Input label="Email" value={brandForm.rep_email} onChange={(v) => setBrandForm((f) => ({ ...f, rep_email: v }))} />
                <Input label="Phone" value={brandForm.rep_phone} onChange={(v) => setBrandForm((f) => ({ ...f, rep_phone: v }))} />
                <Input label="Title" value={brandForm.rep_title} onChange={(v) => setBrandForm((f) => ({ ...f, rep_title: v }))} />
                <Input label="Job Position" value={brandForm.rep_job_position} onChange={(v) => setBrandForm((f) => ({ ...f, rep_job_position: v }))} />
              </div>
            </FormSection>
          </div>

          <div className="flex items-center justify-end gap-3 mt-6 pt-4 border-t border-gray-800">
            <button
              onClick={() => setShowBrandForm(false)}
              className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-gray-200 rounded-lg text-sm transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleBrandSubmit}
              disabled={brandSubmitting || !brandForm.business_name}
              className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
            >
              {brandSubmitting && <RefreshCw className="h-4 w-4 animate-spin" />}
              {editingBrand ? "Update Brand" : "Create Brand"}
            </button>
          </div>
        </Modal>
      )}

      {showCampaignForm && (
        <Modal title={editingCampaign ? "Edit Campaign" : "Create Campaign"} onClose={() => setShowCampaignForm(false)}>
          <div className="space-y-6 max-h-[70vh] overflow-y-auto pr-2">
            <FormSection title="Campaign Details">
              <div className="grid grid-cols-2 gap-3">
                <Input label="Friendly Name *" value={campaignForm.friendly_name} onChange={(v) => setCampaignForm((f) => ({ ...f, friendly_name: v }))} />
                <Select label="Use Case" value={campaignForm.use_case} options={USE_CASES} onChange={(v) => setCampaignForm((f) => ({ ...f, use_case: v }))} />
              </div>
              <div className="mt-3">
                <label className="block text-xs text-gray-400 mb-1">Description</label>
                <textarea
                  value={campaignForm.description}
                  onChange={(e) => setCampaignForm((f) => ({ ...f, description: e.target.value }))}
                  rows={3}
                  className="w-full px-3 py-2 bg-[#1a1a1a] border border-gray-700 rounded-lg text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 resize-none"
                />
              </div>
            </FormSection>

            <FormSection title="Message Samples">
              <div className="space-y-2">
                {campaignForm.message_samples.map((sample, idx) => (
                  <div key={idx} className="flex items-center gap-2">
                    <input
                      type="text"
                      value={sample}
                      onChange={(e) => updateMessageSample(idx, e.target.value)}
                      placeholder={`Sample message ${idx + 1}`}
                      className="flex-1 px-3 py-2 bg-[#1a1a1a] border border-gray-700 rounded-lg text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
                    />
                    {campaignForm.message_samples.length > 1 && (
                      <button
                        onClick={() => removeMessageSample(idx)}
                        className="p-1.5 text-gray-500 hover:text-red-400 transition-colors"
                      >
                        <X className="h-4 w-4" />
                      </button>
                    )}
                  </div>
                ))}
                <button
                  onClick={addMessageSample}
                  className="flex items-center gap-1.5 text-xs text-blue-400 hover:text-blue-300 transition-colors"
                >
                  <Plus className="h-3.5 w-3.5" />
                  Add Sample
                </button>
              </div>
            </FormSection>

            <FormSection title="Message Flow">
              <label className="block text-xs text-gray-400 mb-1">Describe how users opt in to receive messages</label>
              <textarea
                value={campaignForm.message_flow}
                onChange={(e) => setCampaignForm((f) => ({ ...f, message_flow: e.target.value }))}
                rows={3}
                className="w-full px-3 py-2 bg-[#1a1a1a] border border-gray-700 rounded-lg text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 resize-none"
              />
            </FormSection>

            <FormSection title="Content Flags">
              <div className="flex gap-6">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={campaignForm.has_embedded_links}
                    onChange={(e) => setCampaignForm((f) => ({ ...f, has_embedded_links: e.target.checked }))}
                    className="accent-blue-600"
                  />
                  <span className="text-sm text-gray-300">Has Embedded Links</span>
                </label>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={campaignForm.has_embedded_phone}
                    onChange={(e) => setCampaignForm((f) => ({ ...f, has_embedded_phone: e.target.checked }))}
                    className="accent-blue-600"
                  />
                  <span className="text-sm text-gray-300">Has Embedded Phone Numbers</span>
                </label>
              </div>
            </FormSection>

            <FormSection title="Opt-In / Opt-Out / Help">
              <div className="grid grid-cols-2 gap-3">
                <div className="col-span-2">
                  <label className="block text-xs text-gray-400 mb-1">Opt-In Message</label>
                  <textarea
                    value={campaignForm.opt_in_message}
                    onChange={(e) => setCampaignForm((f) => ({ ...f, opt_in_message: e.target.value }))}
                    rows={2}
                    className="w-full px-3 py-2 bg-[#1a1a1a] border border-gray-700 rounded-lg text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 resize-none"
                  />
                </div>
                <Input label="Opt-In Keywords" value={campaignForm.opt_in_keywords} onChange={(v) => setCampaignForm((f) => ({ ...f, opt_in_keywords: v }))} />
                <Input label="Opt-Out Keywords" value={campaignForm.opt_out_keywords} onChange={(v) => setCampaignForm((f) => ({ ...f, opt_out_keywords: v }))} />
                <div className="col-span-2">
                  <label className="block text-xs text-gray-400 mb-1">Opt-Out Message</label>
                  <textarea
                    value={campaignForm.opt_out_message}
                    onChange={(e) => setCampaignForm((f) => ({ ...f, opt_out_message: e.target.value }))}
                    rows={2}
                    className="w-full px-3 py-2 bg-[#1a1a1a] border border-gray-700 rounded-lg text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 resize-none"
                  />
                </div>
                <div className="col-span-2">
                  <label className="block text-xs text-gray-400 mb-1">Help Message</label>
                  <textarea
                    value={campaignForm.help_message}
                    onChange={(e) => setCampaignForm((f) => ({ ...f, help_message: e.target.value }))}
                    rows={2}
                    className="w-full px-3 py-2 bg-[#1a1a1a] border border-gray-700 rounded-lg text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 resize-none"
                  />
                </div>
                <Input label="Help Keywords" value={campaignForm.help_keywords} onChange={(v) => setCampaignForm((f) => ({ ...f, help_keywords: v }))} />
              </div>
            </FormSection>
          </div>

          <div className="flex items-center justify-end gap-3 mt-6 pt-4 border-t border-gray-800">
            <button
              onClick={() => setShowCampaignForm(false)}
              className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-gray-200 rounded-lg text-sm transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleCampaignSubmit}
              disabled={campaignSubmitting || !campaignForm.friendly_name}
              className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
            >
              {campaignSubmitting && <RefreshCw className="h-4 w-4 animate-spin" />}
              {editingCampaign ? "Update Campaign" : "Create Campaign"}
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}

function CampaignCard({
  campaign,
  phoneNumbers,
  actionLoading,
  selectedPhoneNumber,
  onEdit,
  onAction,
  onAssignPhone,
  onRemovePhone,
  onSelectPhone,
}: {
  campaign: Campaign;
  phoneNumbers: PhoneNumberOption[];
  actionLoading: string | null;
  selectedPhoneNumber: Record<string, string>;
  onEdit: () => void;
  onAction: (action: string) => void;
  onAssignPhone: () => void;
  onRemovePhone: (sid: string) => void;
  onSelectPhone: (sid: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const isDraftOrFailed = campaign.status === "draft" || campaign.status === "failed";
  const isPendingOrReview = campaign.status === "pending" || campaign.status === "in_review";
  const assignedSids = campaign.assigned_phone_numbers || [];
  const availableNumbers = phoneNumbers.filter((pn) => !assignedSids.includes(pn.twilio_sid));

  return (
    <div className="bg-[#141414] border border-gray-800 rounded-xl p-5">
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <div className="flex items-center gap-3 mb-1">
            <h3 className="text-base font-semibold text-white">{campaign.friendly_name}</h3>
            <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium ${getStatusBadge(campaign.status)}`}>
              <StatusIcon status={campaign.status} />
              {campaign.status.replace("_", " ")}
            </span>
            <span className="text-xs text-gray-500 bg-gray-800 px-2 py-0.5 rounded">{campaign.use_case}</span>
          </div>
          {campaign.description && (
            <p className="text-sm text-gray-400 mt-1">{campaign.description}</p>
          )}
        </div>
        <div className="flex items-center gap-2">
          {isDraftOrFailed && (
            <>
              <button onClick={onEdit} className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-700 hover:bg-gray-600 text-gray-200 rounded-lg text-xs transition-colors">
                <Edit3 className="h-3.5 w-3.5" />
                Edit
              </button>
              <button
                onClick={() => onAction("submit")}
                disabled={actionLoading === `campaign-submit-${campaign.id}`}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-xs transition-colors disabled:opacity-50"
              >
                <Send className="h-3.5 w-3.5" />
                {actionLoading === `campaign-submit-${campaign.id}` ? "Submitting..." : "Submit"}
              </button>
              <button
                onClick={() => onAction("delete")}
                disabled={actionLoading === `campaign-delete-${campaign.id}`}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-red-600/20 hover:bg-red-600/30 text-red-400 rounded-lg text-xs transition-colors disabled:opacity-50"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </>
          )}
          {isPendingOrReview && (
            <button
              onClick={() => onAction("refresh")}
              disabled={actionLoading === `campaign-refresh-${campaign.id}`}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-700 hover:bg-gray-600 text-gray-200 rounded-lg text-xs transition-colors disabled:opacity-50"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${actionLoading === `campaign-refresh-${campaign.id}` ? "animate-spin" : ""}`} />
              Refresh Status
            </button>
          )}
          <button
            onClick={() => setExpanded(!expanded)}
            className="p-1.5 text-gray-500 hover:text-gray-300 transition-colors"
          >
            {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          </button>
        </div>
      </div>

      {campaign.failure_reason && (
        <div className="flex items-start gap-2 mt-3 p-3 bg-red-500/10 border border-red-500/20 rounded-lg">
          <AlertCircle className="h-4 w-4 text-red-400 mt-0.5 flex-shrink-0" />
          <p className="text-sm text-red-300">{campaign.failure_reason}</p>
        </div>
      )}

      {expanded && (
        <div className="mt-4 pt-4 border-t border-gray-800 space-y-4">
          {campaign.twilio_messaging_service_sid && (
            <div className="text-xs text-gray-500">
              Messaging Service: <span className="text-gray-400">{campaign.twilio_messaging_service_sid}</span>
            </div>
          )}
          {campaign.twilio_campaign_sid && (
            <div className="text-xs text-gray-500">
              Campaign SID: <span className="text-gray-400">{campaign.twilio_campaign_sid}</span>
            </div>
          )}

          <div>
            <div className="flex items-center gap-2 mb-2">
              <Phone className="h-4 w-4 text-gray-500" />
              <h4 className="text-sm font-medium text-gray-300">Phone Numbers</h4>
            </div>

            {assignedSids.length > 0 && (
              <div className="space-y-2 mb-3">
                {assignedSids.map((sid) => {
                  const pn = phoneNumbers.find((p) => p.twilio_sid === sid);
                  return (
                    <div key={sid} className="flex items-center justify-between bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2">
                      <div className="text-sm text-gray-300">
                        {pn ? `${pn.phone_number} (${pn.friendly_name || sid})` : sid}
                      </div>
                      <button
                        onClick={() => onRemovePhone(sid)}
                        disabled={actionLoading === `remove-${campaign.id}-${sid}`}
                        className="text-xs text-red-400 hover:text-red-300 transition-colors disabled:opacity-50"
                      >
                        {actionLoading === `remove-${campaign.id}-${sid}` ? "Removing..." : "Remove"}
                      </button>
                    </div>
                  );
                })}
              </div>
            )}

            {availableNumbers.length > 0 && (
              <div className="flex items-center gap-2">
                <select
                  value={selectedPhoneNumber[campaign.id] || ""}
                  onChange={(e) => onSelectPhone(e.target.value)}
                  className="flex-1 px-3 py-2 bg-[#1a1a1a] border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
                >
                  <option value="">Select a phone number...</option>
                  {availableNumbers.map((pn) => (
                    <option key={pn.twilio_sid} value={pn.twilio_sid}>
                      {pn.phone_number} {pn.friendly_name ? `(${pn.friendly_name})` : ""}
                    </option>
                  ))}
                </select>
                <button
                  onClick={onAssignPhone}
                  disabled={!selectedPhoneNumber[campaign.id] || actionLoading === `assign-${campaign.id}`}
                  className="flex items-center gap-1.5 px-3 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm transition-colors disabled:opacity-50"
                >
                  <Plus className="h-4 w-4" />
                  {actionLoading === `assign-${campaign.id}` ? "Assigning..." : "Assign"}
                </button>
              </div>
            )}

            {assignedSids.length === 0 && availableNumbers.length === 0 && (
              <p className="text-xs text-gray-500">No phone numbers available</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-[#141414] border border-gray-800 rounded-xl w-full max-w-2xl mx-4 p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-white">{title}</h2>
          <button onClick={onClose} className="p-1 text-gray-500 hover:text-gray-300 transition-colors">
            <X className="h-5 w-5" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function FormSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="text-sm font-medium text-gray-300 mb-3">{title}</h3>
      {children}
    </div>
  );
}

function Input({
  label,
  value,
  onChange,
  className = "",
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  className?: string;
}) {
  return (
    <div className={className}>
      <label className="block text-xs text-gray-400 mb-1">{label}</label>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full px-3 py-2 bg-[#1a1a1a] border border-gray-700 rounded-lg text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
      />
    </div>
  );
}

function Select({
  label,
  value,
  options,
  labels,
  onChange,
}: {
  label: string;
  value: string;
  options: string[];
  labels?: string[];
  onChange: (v: string) => void;
}) {
  return (
    <div>
      <label className="block text-xs text-gray-400 mb-1">{label}</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full px-3 py-2 bg-[#1a1a1a] border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
      >
        <option value="">Select...</option>
        {options.map((opt, i) => (
          <option key={opt} value={opt}>
            {labels ? labels[i] : opt}
          </option>
        ))}
      </select>
    </div>
  );
}
