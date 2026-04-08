"use client";

import { useState } from "react";
import { RefreshCw } from "lucide-react";
import { toast } from "sonner";
import type { Brand } from "../types";
import { BUSINESS_TYPES, BUSINESS_INDUSTRIES, COMPANY_TYPES, BRAND_TYPES, defaultBrandForm } from "../types";
import { Modal, FormSection, Input, Select } from "./FormElements";

interface BrandModalProps {
  brand: Brand | null;
  accountId: string;
  onClose: () => void;
  onSave: () => void;
}

export default function BrandModal({ brand, accountId, onClose, onSave }: BrandModalProps) {
  const [form, setForm] = useState(brand ? {
    business_name: brand.business_name || "",
    business_type: brand.business_type || "",
    business_industry: brand.business_industry || "",
    ein: brand.ein || "",
    ein_issuing_country: brand.ein_issuing_country || "US",
    company_type: brand.company_type || "",
    website_url: brand.website_url || "",
    street: brand.street || "",
    city: brand.city || "",
    region: brand.region || "",
    postal_code: brand.postal_code || "",
    country: brand.country || "US",
    rep_first_name: brand.rep_first_name || "",
    rep_last_name: brand.rep_last_name || "",
    rep_email: brand.rep_email || "",
    rep_phone: brand.rep_phone || "",
    rep_title: brand.rep_title || "",
    rep_job_position: brand.rep_job_position || "",
    brand_type: brand.brand_type || "standard",
  } : { ...defaultBrandForm });
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async () => {
    if (!accountId) return;
    setSubmitting(true);
    try {
      const url = brand ? `/api/sms-compliance/brands/${brand.id}` : `/api/sms-compliance/brands`;
      const method = brand ? "PUT" : "POST";
      const body = brand ? { ...form } : { ...form, account_id: accountId };
      const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        toast.success(brand ? "Brand updated" : "Brand created");
        onClose();
        onSave();
      } else {
        const err = await res.json();
        toast.error(err.detail || "Failed to save brand");
      }
    } catch {
      toast.error("Failed to save brand");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal title={brand ? "Edit Brand" : "Register Brand"} onClose={onClose}>
      <div className="space-y-6 max-h-[70vh] overflow-y-auto pr-2">
        <FormSection title="Brand Type">
          <div className="flex flex-wrap gap-3">
            {BRAND_TYPES.map((bt) => (
              <label key={bt.value} className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  name="brand_type"
                  value={bt.value}
                  checked={form.brand_type === bt.value}
                  onChange={(e) => setForm((f) => ({ ...f, brand_type: e.target.value }))}
                  className="accent-blue-600"
                />
                <span className="text-sm text-gray-300">{bt.label}</span>
              </label>
            ))}
          </div>
        </FormSection>

        <FormSection title="Business Information">
          <div className="grid grid-cols-2 gap-3">
            <Input label="Business Name *" value={form.business_name} onChange={(v) => setForm((f) => ({ ...f, business_name: v }))} />
            <Select label="Business Type" value={form.business_type} options={BUSINESS_TYPES} onChange={(v) => setForm((f) => ({ ...f, business_type: v }))} />
            <Select label="Business Industry" value={form.business_industry} options={BUSINESS_INDUSTRIES} onChange={(v) => setForm((f) => ({ ...f, business_industry: v }))} />
            <Input label="EIN" value={form.ein} onChange={(v) => setForm((f) => ({ ...f, ein: v }))} />
            <Input label="EIN Issuing Country" value={form.ein_issuing_country} onChange={(v) => setForm((f) => ({ ...f, ein_issuing_country: v }))} />
            <Select label="Company Type" value={form.company_type} options={COMPANY_TYPES.map((ct) => ct.value)} labels={COMPANY_TYPES.map((ct) => ct.label)} onChange={(v) => setForm((f) => ({ ...f, company_type: v }))} />
            <Input label="Website URL" value={form.website_url} onChange={(v) => setForm((f) => ({ ...f, website_url: v }))} className="col-span-2" />
          </div>
        </FormSection>

        <FormSection title="Address">
          <div className="grid grid-cols-2 gap-3">
            <Input label="Street" value={form.street} onChange={(v) => setForm((f) => ({ ...f, street: v }))} className="col-span-2" />
            <Input label="City" value={form.city} onChange={(v) => setForm((f) => ({ ...f, city: v }))} />
            <Input label="State/Region" value={form.region} onChange={(v) => setForm((f) => ({ ...f, region: v }))} />
            <Input label="Postal Code" value={form.postal_code} onChange={(v) => setForm((f) => ({ ...f, postal_code: v }))} />
            <Input label="Country" value={form.country} onChange={(v) => setForm((f) => ({ ...f, country: v }))} />
          </div>
        </FormSection>

        <FormSection title="Authorized Representative">
          <div className="grid grid-cols-2 gap-3">
            <Input label="First Name" value={form.rep_first_name} onChange={(v) => setForm((f) => ({ ...f, rep_first_name: v }))} />
            <Input label="Last Name" value={form.rep_last_name} onChange={(v) => setForm((f) => ({ ...f, rep_last_name: v }))} />
            <Input label="Email" value={form.rep_email} onChange={(v) => setForm((f) => ({ ...f, rep_email: v }))} />
            <Input label="Phone" value={form.rep_phone} onChange={(v) => setForm((f) => ({ ...f, rep_phone: v }))} />
            <Input label="Title" value={form.rep_title} onChange={(v) => setForm((f) => ({ ...f, rep_title: v }))} />
            <Input label="Job Position" value={form.rep_job_position} onChange={(v) => setForm((f) => ({ ...f, rep_job_position: v }))} />
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
          disabled={submitting || !form.business_name}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
        >
          {submitting && <RefreshCw className="h-4 w-4 animate-spin" />}
          {brand ? "Update Brand" : "Create Brand"}
        </button>
      </div>
    </Modal>
  );
}
