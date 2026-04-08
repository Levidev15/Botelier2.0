"use client";

import { useState } from "react";
import {
  Edit3, Send, Trash2, RefreshCw, ChevronDown, ChevronUp, AlertCircle, Phone, Plus,
} from "lucide-react";
import { getStatusBadge, StatusIcon } from "../types";
import type { Campaign, PhoneNumberOption } from "../types";

interface CampaignCardProps {
  campaign: Campaign;
  phoneNumbers: PhoneNumberOption[];
  actionLoading: string | null;
  selectedPhoneNumber: Record<string, string>;
  onEdit: () => void;
  onAction: (action: string) => void;
  onAssignPhone: () => void;
  onRemovePhone: (sid: string) => void;
  onSelectPhone: (sid: string) => void;
}

export default function CampaignCard({
  campaign,
  phoneNumbers,
  actionLoading,
  selectedPhoneNumber,
  onEdit,
  onAction,
  onAssignPhone,
  onRemovePhone,
  onSelectPhone,
}: CampaignCardProps) {
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
