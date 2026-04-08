"use client";

import { Shield, Plus, Edit3, Trash2, Send, RefreshCw, AlertCircle } from "lucide-react";
import type { Brand } from "../types";
import { getStatusBadge, StatusIcon } from "../types";

interface BrandSectionProps {
  brand: Brand | null;
  actionLoading: string | null;
  onCreateBrand: () => void;
  onEditBrand: (brand: Brand) => void;
  onBrandAction: (action: string, brandId: string) => void;
}

export default function BrandSection({ brand, actionLoading, onCreateBrand, onEditBrand, onBrandAction }: BrandSectionProps) {
  return (
    <section>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-white">Brand Registration</h2>
        {!brand && (
          <button
            onClick={onCreateBrand}
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
                    onClick={() => onEditBrand(brand)}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-700 hover:bg-gray-600 text-gray-200 rounded-lg text-xs transition-colors"
                  >
                    <Edit3 className="h-3.5 w-3.5" />
                    Edit
                  </button>
                  <button
                    onClick={() => onBrandAction("submit", brand.id)}
                    disabled={actionLoading === `brand-submit-${brand.id}`}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-xs transition-colors disabled:opacity-50"
                  >
                    <Send className="h-3.5 w-3.5" />
                    {actionLoading === `brand-submit-${brand.id}` ? "Submitting..." : "Submit to Twilio"}
                  </button>
                  <button
                    onClick={() => onBrandAction("delete", brand.id)}
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
                  onClick={() => onBrandAction("refresh", brand.id)}
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
                {[brand.street, brand.city, brand.region, brand.postal_code, brand.country].filter(Boolean).join(", ") || "—"}
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
            onClick={onCreateBrand}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium transition-colors"
          >
            <Plus className="h-4 w-4" />
            Register Brand
          </button>
        </div>
      )}
    </section>
  );
}
