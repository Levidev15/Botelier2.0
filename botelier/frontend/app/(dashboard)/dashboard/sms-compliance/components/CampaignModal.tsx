"use client";

import { useState } from "react";
import { RefreshCw, Plus, X } from "lucide-react";
import { toast } from "sonner";
import type { Brand, Campaign } from "../types";
import { USE_CASES, defaultCampaignForm } from "../types";
import { Modal, FormSection, Input, Select } from "./FormElements";

interface CampaignModalProps {
  campaign: Campaign | null;
  brand: Brand;
  accountId: string;
  onClose: () => void;
  onSave: () => void;
}

export default function CampaignModal({ campaign, brand, accountId, onClose, onSave }: CampaignModalProps) {
  const [form, setForm] = useState(campaign ? {
    friendly_name: campaign.friendly_name || "",
    use_case: campaign.use_case || "CUSTOMER_CARE",
    description: campaign.description || "",
    message_samples: campaign.message_samples?.length > 0 ? [...campaign.message_samples] : [""],
    message_flow: campaign.message_flow || "",
    has_embedded_links: campaign.has_embedded_links || false,
    has_embedded_phone: campaign.has_embedded_phone || false,
    opt_in_message: campaign.opt_in_message || "",
    opt_in_keywords: campaign.opt_in_keywords || "YES,START",
    opt_out_message: campaign.opt_out_message || "",
    opt_out_keywords: campaign.opt_out_keywords || "STOP,END,CANCEL,UNSUBSCRIBE,QUIT",
    help_message: campaign.help_message || "",
    help_keywords: campaign.help_keywords || "HELP,INFO",
  } : { ...defaultCampaignForm });
  const [submitting, setSubmitting] = useState(false);

  const addMessageSample = () => setForm((prev) => ({ ...prev, message_samples: [...prev.message_samples, ""] }));
  const removeMessageSample = (idx: number) => setForm((prev) => ({ ...prev, message_samples: prev.message_samples.filter((_, i) => i !== idx) }));
  const updateMessageSample = (idx: number, value: string) => setForm((prev) => ({ ...prev, message_samples: prev.message_samples.map((s, i) => (i === idx ? value : s)) }));

  const handleSubmit = async () => {
    if (!accountId || !brand) return;
    setSubmitting(true);
    try {
      const url = campaign ? `/api/sms-compliance/campaigns/${campaign.id}` : `/api/sms-compliance/campaigns`;
      const method = campaign ? "PUT" : "POST";
      const samples = form.message_samples.filter((s) => s.trim() !== "");
      const body = campaign
        ? { ...form, message_samples: samples }
        : { ...form, message_samples: samples, brand_id: brand.id, account_id: accountId };
      const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        toast.success(campaign ? "Campaign updated" : "Campaign created");
        onClose();
        onSave();
      } else {
        const err = await res.json();
        toast.error(err.detail || "Failed to save campaign");
      }
    } catch {
      toast.error("Failed to save campaign");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal title={campaign ? "Edit Campaign" : "Create Campaign"} onClose={onClose}>
      <div className="space-y-6 max-h-[70vh] overflow-y-auto pr-2">
        <FormSection title="Campaign Details">
          <div className="grid grid-cols-2 gap-3">
            <Input label="Friendly Name *" value={form.friendly_name} onChange={(v) => setForm((f) => ({ ...f, friendly_name: v }))} />
            <Select label="Use Case" value={form.use_case} options={USE_CASES} onChange={(v) => setForm((f) => ({ ...f, use_case: v }))} />
          </div>
          <div className="mt-3">
            <label className="block text-xs text-gray-400 mb-1">Description</label>
            <textarea
              value={form.description}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              rows={3}
              className="w-full px-3 py-2 bg-[#1a1a1a] border border-gray-700 rounded-lg text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 resize-none"
            />
          </div>
        </FormSection>

        <FormSection title="Message Samples">
          <div className="space-y-2">
            {form.message_samples.map((sample, idx) => (
              <div key={idx} className="flex items-center gap-2">
                <input
                  type="text"
                  value={sample}
                  onChange={(e) => updateMessageSample(idx, e.target.value)}
                  placeholder={`Sample message ${idx + 1}`}
                  className="flex-1 px-3 py-2 bg-[#1a1a1a] border border-gray-700 rounded-lg text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
                />
                {form.message_samples.length > 1 && (
                  <button onClick={() => removeMessageSample(idx)} className="p-1.5 text-gray-500 hover:text-red-400 transition-colors">
                    <X className="h-4 w-4" />
                  </button>
                )}
              </div>
            ))}
            <button onClick={addMessageSample} className="flex items-center gap-1.5 text-xs text-blue-400 hover:text-blue-300 transition-colors">
              <Plus className="h-3.5 w-3.5" />
              Add Sample
            </button>
          </div>
        </FormSection>

        <FormSection title="Message Flow">
          <label className="block text-xs text-gray-400 mb-1">Describe how users opt in to receive messages</label>
          <textarea
            value={form.message_flow}
            onChange={(e) => setForm((f) => ({ ...f, message_flow: e.target.value }))}
            rows={3}
            className="w-full px-3 py-2 bg-[#1a1a1a] border border-gray-700 rounded-lg text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 resize-none"
          />
        </FormSection>

        <FormSection title="Content Flags">
          <div className="flex gap-6">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={form.has_embedded_links}
                onChange={(e) => setForm((f) => ({ ...f, has_embedded_links: e.target.checked }))}
                className="accent-blue-600"
              />
              <span className="text-sm text-gray-300">Has Embedded Links</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={form.has_embedded_phone}
                onChange={(e) => setForm((f) => ({ ...f, has_embedded_phone: e.target.checked }))}
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
                value={form.opt_in_message}
                onChange={(e) => setForm((f) => ({ ...f, opt_in_message: e.target.value }))}
                rows={2}
                className="w-full px-3 py-2 bg-[#1a1a1a] border border-gray-700 rounded-lg text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 resize-none"
              />
            </div>
            <Input label="Opt-In Keywords" value={form.opt_in_keywords} onChange={(v) => setForm((f) => ({ ...f, opt_in_keywords: v }))} />
            <Input label="Opt-Out Keywords" value={form.opt_out_keywords} onChange={(v) => setForm((f) => ({ ...f, opt_out_keywords: v }))} />
            <div className="col-span-2">
              <label className="block text-xs text-gray-400 mb-1">Opt-Out Message</label>
              <textarea
                value={form.opt_out_message}
                onChange={(e) => setForm((f) => ({ ...f, opt_out_message: e.target.value }))}
                rows={2}
                className="w-full px-3 py-2 bg-[#1a1a1a] border border-gray-700 rounded-lg text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 resize-none"
              />
            </div>
            <div className="col-span-2">
              <label className="block text-xs text-gray-400 mb-1">Help Message</label>
              <textarea
                value={form.help_message}
                onChange={(e) => setForm((f) => ({ ...f, help_message: e.target.value }))}
                rows={2}
                className="w-full px-3 py-2 bg-[#1a1a1a] border border-gray-700 rounded-lg text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 resize-none"
              />
            </div>
            <Input label="Help Keywords" value={form.help_keywords} onChange={(v) => setForm((f) => ({ ...f, help_keywords: v }))} />
          </div>
        </FormSection>
      </div>

      <div className="flex items-center justify-end gap-3 mt-6 pt-4 border-t border-gray-800">
        <button
          onClick={onClose}
          className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-gray-200 rounded-lg text-sm transition-colors"
        >
          Cancel
        </button>
        <button
          onClick={handleSubmit}
          disabled={submitting || !form.friendly_name}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
        >
          {submitting && <RefreshCw className="h-4 w-4 animate-spin" />}
          {campaign ? "Update Campaign" : "Create Campaign"}
        </button>
      </div>
    </Modal>
  );
}
