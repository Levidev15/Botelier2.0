"use client";

import { useState, useEffect } from "react";
import { Shield, Plus, RefreshCw, AlertCircle, Clock, Send } from "lucide-react";
import { useAccountContext } from "@/lib/auth/useAccountContext";
import { toast } from "sonner";
import type { Brand, Campaign, PhoneNumberOption } from "./types";
import CampaignCard from "./components/CampaignCard";
import BrandModal from "./components/BrandModal";
import CampaignModal from "./components/CampaignModal";
import BrandSection from "./components/BrandSection";

export default function SMSCompliancePage() {
  const { accountId, loading: contextLoading } = useAccountContext();

  const [brands, setBrands] = useState<Brand[]>([]);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [phoneNumbers, setPhoneNumbers] = useState<PhoneNumberOption[]>([]);
  const [loading, setLoading] = useState(true);

  const [showBrandForm, setShowBrandForm] = useState(false);
  const [editingBrand, setEditingBrand] = useState<Brand | null>(null);

  const [showCampaignForm, setShowCampaignForm] = useState(false);
  const [editingCampaign, setEditingCampaign] = useState<Campaign | null>(null);

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
      const res = await fetch(`/api/sms-compliance/campaigns?account_id=${accountId}`);
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
      const res = await fetch(`/api/sms-compliance/accounts/${accountId}/phone-numbers`);
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

  const openBrandCreate = () => { setEditingBrand(null); setShowBrandForm(true); };
  const openBrandEdit = (b: Brand) => { setEditingBrand(b); setShowBrandForm(true); };

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

  const openCampaignCreate = () => { setEditingCampaign(null); setShowCampaignForm(true); };
  const openCampaignEdit = (c: Campaign) => { setEditingCampaign(c); setShowCampaignForm(true); };

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

        <BrandSection
          brand={brand}
          actionLoading={actionLoading}
          onCreateBrand={openBrandCreate}
          onEditBrand={openBrandEdit}
          onBrandAction={handleBrandAction}
        />

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

      {showBrandForm && accountId && (
        <BrandModal
          brand={editingBrand}
          accountId={accountId}
          onClose={() => setShowBrandForm(false)}
          onSave={fetchBrands}
        />
      )}

      {showCampaignForm && accountId && brand && (
        <CampaignModal
          campaign={editingCampaign}
          brand={brand}
          accountId={accountId}
          onClose={() => setShowCampaignForm(false)}
          onSave={fetchCampaigns}
        />
      )}
    </div>
  );
}
