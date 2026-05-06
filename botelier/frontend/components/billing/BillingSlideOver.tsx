"use client";

import { useEffect, useState, useCallback } from "react";
import {
  X,
  AlertTriangle,
  RefreshCw,
  Loader2,
  ChevronDown,
  ChevronRight,
  Save,
  Info,
} from "lucide-react";
import { toast } from "sonner";
import { useAuthToken } from "@/lib/auth/useAuthToken";

// ──────────────────────────────────────────────────────────────────────────────
// Types
// ──────────────────────────────────────────────────────────────────────────────

interface RateConfig {
  id: string;
  inbound_rate_usd: number;
  outbound_rate_usd: number;
  sms_inbound_rate_usd: number;
  sms_outbound_rate_usd: number;
  monthly_alert_threshold_usd: number | null;
  effective_from: string | null;
}

interface AccountSummary {
  inbound_calls: number;
  inbound_minutes: number;
  inbound_cost_usd: number;
  outbound_transfers: number;
  outbound_minutes: number;
  outbound_cost_usd: number;
  sms_inbound_count: number;
  sms_outbound_count: number;
  sms_cost_usd: number;
  billable_total_usd: number;
  llm_prompt_tokens: number;
  llm_completion_tokens: number;
  llm_cost_usd: number;
  tts_characters: number;
  tts_cost_usd: number;
  stt_seconds: number;
  stt_cost_usd: number;
  internal_cost_usd: number;
  margin_usd: number;
}

interface CallRow {
  call_log_id: string;
  reference_id: string | null;
  started_at: string | null;
  caller_number: string | null;
  assistant_name: string | null;
  duration_seconds: number;
  billable_inbound_minutes: number;
  inbound_cost_usd: number;
  total_cost_usd: number;
  has_transfers: boolean;
  billing_items: Array<{
    item_type: string;
    quantity_minutes: number;
    cost_usd: number;
    destination?: string | null;
    leg_type?: string | null;
    leg_duration_seconds?: number;
  }>;
}

interface AccountDetail {
  account_id: string;
  account_name: string;
  period_start: string;
  period_end: string;
  summary: AccountSummary;
  mtd_total_usd: number;
  alert_threshold_usd: number | null;
  rate_config: RateConfig | null;
  calls: {
    items: CallRow[];
    total: number;
    page: number;
    per_page: number;
    pages: number;
  };
}

// ──────────────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────────────

function fmt$(n: number) {
  return `$${n.toFixed(4)}`;
}

function fmtDuration(secs: number) {
  if (secs < 60) return `${secs}s`;
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return s > 0 ? `${m}m ${s}s` : `${m}m`;
}

function SkeletonCard() {
  return (
    <div className="bg-[#0a0a0a] border border-[#1a1a1a] rounded-lg p-4 space-y-2 animate-pulse">
      <div className="h-3 bg-[#222222] rounded w-24" />
      <div className="h-6 bg-[#222222] rounded w-16" />
      <div className="h-3 bg-[#1a1a1a] rounded w-20" />
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────────────
// BillingSlideOver
// ──────────────────────────────────────────────────────────────────────────────

interface BillingSlideOverProps {
  accountId: string | null;
  onClose: () => void;
}

export default function BillingSlideOver({
  accountId,
  onClose,
}: BillingSlideOverProps) {
  const { authFetch } = useAuthToken();
  const [detail, setDetail] = useState<AccountDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Rate form state
  const [rateForm, setRateForm] = useState({
    inbound_rate_usd: "",
    outbound_rate_usd: "",
    sms_inbound_rate_usd: "",
    sms_outbound_rate_usd: "",
    monthly_alert_threshold_usd: "",
  });
  const [saving, setSaving] = useState(false);

  // Expanded call rows
  const [expandedCalls, setExpandedCalls] = useState<Set<string>>(new Set());

  const fetchDetail = useCallback(async () => {
    if (!accountId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await authFetch(
        `/api/admin/billing/accounts/${accountId}/detail?period=mtd&per_page=10`
      );
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to load account billing detail");
      }
      const data: AccountDetail = await res.json();
      setDetail(data);
      // Pre-fill rate form from current config
      if (data.rate_config) {
        const c = data.rate_config;
        setRateForm({
          inbound_rate_usd: c.inbound_rate_usd.toString(),
          outbound_rate_usd: c.outbound_rate_usd.toString(),
          sms_inbound_rate_usd: c.sms_inbound_rate_usd.toString(),
          sms_outbound_rate_usd: c.sms_outbound_rate_usd.toString(),
          monthly_alert_threshold_usd:
            c.monthly_alert_threshold_usd != null
              ? c.monthly_alert_threshold_usd.toString()
              : "",
        });
      }
    } catch (e: any) {
      setError(e.message || "Failed to load data");
    } finally {
      setLoading(false);
    }
  }, [accountId, authFetch]);

  useEffect(() => {
    if (accountId) {
      setDetail(null);
      setExpandedCalls(new Set());
      fetchDetail();
    }
  }, [accountId, fetchDetail]);

  const handleSaveRates = async () => {
    if (!accountId) return;
    const inbound = parseFloat(rateForm.inbound_rate_usd);
    const outbound = parseFloat(rateForm.outbound_rate_usd);
    const smsIn = parseFloat(rateForm.sms_inbound_rate_usd);
    const smsOut = parseFloat(rateForm.sms_outbound_rate_usd);
    const threshold =
      rateForm.monthly_alert_threshold_usd.trim() !== ""
        ? parseFloat(rateForm.monthly_alert_threshold_usd)
        : null;

    if ([inbound, outbound, smsIn, smsOut].some((v) => isNaN(v) || v < 0)) {
      toast.error("All rates must be non-negative numbers");
      return;
    }
    if (threshold !== null && (isNaN(threshold) || threshold < 0)) {
      toast.error("Alert threshold must be a non-negative number");
      return;
    }

    setSaving(true);
    try {
      const res = await authFetch(
        `/api/admin/billing/accounts/${accountId}/config`,
        {
          method: "PUT",
          body: JSON.stringify({
            inbound_rate_usd: inbound,
            outbound_rate_usd: outbound,
            sms_inbound_rate_usd: smsIn,
            sms_outbound_rate_usd: smsOut,
            monthly_alert_threshold_usd: threshold,
          }),
        }
      );
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to save rates");
      }
      toast.success("Billing rates updated");
      fetchDetail();
    } catch (e: any) {
      toast.error(e.message || "Failed to save rates");
    } finally {
      setSaving(false);
    }
  };

  if (!accountId) return null;

  const toggleCall = (id: string) => {
    setExpandedCalls((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const threshold = detail?.alert_threshold_usd ?? null;
  const mtd = detail?.mtd_total_usd ?? 0;
  const thresholdExceeded = threshold !== null && mtd >= threshold;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/60"
        onClick={onClose}
        aria-hidden
      />

      {/* Panel */}
      <div className="relative w-[700px] max-w-full h-full bg-[#111111] border-l border-[#222222] flex flex-col overflow-hidden z-10 shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[#222222] flex-shrink-0">
          <div>
            <h2 className="text-lg font-semibold text-white">
              {detail?.account_name ?? "Account Billing"}
            </h2>
            <p className="text-xs text-gray-500 mt-0.5">
              Month-to-date summary &amp; rate configuration
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-gray-400 hover:text-white hover:bg-[#222222] rounded-lg transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-6">
          {/* Alert threshold banner */}
          {detail && thresholdExceeded && (
            <div className="flex items-start gap-3 px-4 py-3 bg-yellow-500/10 border border-yellow-500/30 rounded-lg">
              <AlertTriangle className="h-5 w-5 text-yellow-400 flex-shrink-0 mt-0.5" />
              <p className="text-sm text-yellow-300">
                This account has reached their{" "}
                <span className="font-semibold">
                  ${threshold!.toFixed(2)}
                </span>{" "}
                monthly alert threshold. MTD spend:{" "}
                <span className="font-semibold">${mtd.toFixed(2)}</span>.
              </p>
            </div>
          )}
          {detail && !thresholdExceeded && threshold === null && (
            <div className="flex items-center gap-2 px-4 py-2.5 bg-[#0a0a0a] border border-[#1a1a1a] rounded-lg">
              <Info className="h-4 w-4 text-gray-600 flex-shrink-0" />
              <p className="text-xs text-gray-600">No alert threshold configured.</p>
            </div>
          )}

          {/* Error state */}
          {error && (
            <div className="flex flex-col items-center gap-4 py-12">
              <p className="text-red-400 text-sm">{error}</p>
              <button
                onClick={fetchDetail}
                className="flex items-center gap-2 px-4 py-2 bg-[#1a1a1a] hover:bg-[#222222] text-gray-300 rounded-lg transition-colors text-sm"
              >
                <RefreshCw className="h-4 w-4" />
                Retry
              </button>
            </div>
          )}

          {/* Loading */}
          {loading && !detail && (
            <>
              <Section title="Summary">
                <div className="grid grid-cols-2 gap-3">
                  {[...Array(4)].map((_, i) => (
                    <SkeletonCard key={i} />
                  ))}
                </div>
              </Section>
              <Section title="Internal Cost (Admin Only)" amber>
                <div className="grid grid-cols-2 gap-3">
                  {[...Array(4)].map((_, i) => (
                    <SkeletonCard key={i} />
                  ))}
                </div>
              </Section>
            </>
          )}

          {/* Data */}
          {detail && !loading && (
            <>
              {/* ── Summary cards ── */}
              <Section title="Summary">
                <div className="grid grid-cols-2 gap-3">
                  <StatCard
                    label="Inbound Minutes"
                    value={detail.summary.inbound_minutes.toLocaleString()}
                    sub={`${detail.summary.inbound_calls} calls · ${fmt$(detail.summary.inbound_cost_usd)}`}
                  />
                  <StatCard
                    label="Outbound Minutes"
                    value={detail.summary.outbound_minutes.toLocaleString()}
                    sub={`${detail.summary.outbound_transfers} transfers · ${fmt$(detail.summary.outbound_cost_usd)}`}
                  />
                  <StatCard
                    label="SMS Messages"
                    value={(
                      detail.summary.sms_inbound_count +
                      detail.summary.sms_outbound_count
                    ).toLocaleString()}
                    sub={`In: ${detail.summary.sms_inbound_count} · Out: ${detail.summary.sms_outbound_count} · ${fmt$(detail.summary.sms_cost_usd)}`}
                  />
                  <StatCard
                    label="Total Billable"
                    value={`$${detail.summary.billable_total_usd.toFixed(4)}`}
                    sub={`MTD: $${detail.mtd_total_usd.toFixed(4)}`}
                    highlight
                  />
                </div>
              </Section>

              {/* ── Internal cost (admin only) ── */}
              <Section title="Internal Cost (Admin Only)" amber>
                <div className="grid grid-cols-2 gap-3">
                  <StatCard
                    label="LLM Cost"
                    value={fmt$(detail.summary.llm_cost_usd)}
                    sub={`${detail.summary.llm_prompt_tokens.toLocaleString()} prompt · ${detail.summary.llm_completion_tokens.toLocaleString()} completion tokens`}
                    amber
                  />
                  <StatCard
                    label="TTS Cost"
                    value={fmt$(detail.summary.tts_cost_usd)}
                    sub={`${detail.summary.tts_characters.toLocaleString()} characters`}
                    amber
                  />
                  <StatCard
                    label="STT Cost"
                    value={fmt$(detail.summary.stt_cost_usd)}
                    sub={`${detail.summary.stt_seconds.toFixed(1)}s`}
                    amber
                  />
                  <StatCard
                    label="Total Internal"
                    value={fmt$(detail.summary.internal_cost_usd)}
                    sub={`Margin: ${fmt$(detail.summary.margin_usd)}`}
                    highlight
                    amber
                  />
                </div>
              </Section>

              {/* ── Rate configuration ── */}
              <Section title="Billing Rates">
                {detail.rate_config && (
                  <p className="text-xs text-gray-500 mb-4">
                    Effective from{" "}
                    <span className="text-gray-400">
                      {new Date(
                        detail.rate_config.effective_from!
                      ).toLocaleString()}
                    </span>
                  </p>
                )}
                <div className="grid grid-cols-2 gap-4">
                  <RateField
                    label="Inbound Rate ($/min)"
                    value={rateForm.inbound_rate_usd}
                    onChange={(v) =>
                      setRateForm((f) => ({ ...f, inbound_rate_usd: v }))
                    }
                  />
                  <RateField
                    label="Outbound Rate ($/min)"
                    value={rateForm.outbound_rate_usd}
                    onChange={(v) =>
                      setRateForm((f) => ({ ...f, outbound_rate_usd: v }))
                    }
                  />
                  <RateField
                    label="SMS Inbound ($/msg)"
                    value={rateForm.sms_inbound_rate_usd}
                    onChange={(v) =>
                      setRateForm((f) => ({
                        ...f,
                        sms_inbound_rate_usd: v,
                      }))
                    }
                  />
                  <RateField
                    label="SMS Outbound ($/msg)"
                    value={rateForm.sms_outbound_rate_usd}
                    onChange={(v) =>
                      setRateForm((f) => ({
                        ...f,
                        sms_outbound_rate_usd: v,
                      }))
                    }
                  />
                </div>
                <div className="mt-4">
                  <label className="block text-xs font-medium text-gray-400 mb-1">
                    Monthly Alert Threshold ($, leave blank to disable)
                  </label>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    value={rateForm.monthly_alert_threshold_usd}
                    onChange={(e) =>
                      setRateForm((f) => ({
                        ...f,
                        monthly_alert_threshold_usd: e.target.value,
                      }))
                    }
                    placeholder="No threshold"
                    className="w-48 px-3 py-2 bg-[#0a0a0a] border border-[#222222] rounded-lg text-white text-sm focus:outline-none focus:border-blue-600"
                  />
                </div>
                <div className="mt-4 flex justify-end">
                  <button
                    onClick={handleSaveRates}
                    disabled={saving}
                    className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm rounded-lg transition-colors"
                  >
                    {saving ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Save className="h-4 w-4" />
                    )}
                    Save Rates
                  </button>
                </div>
              </Section>

              {/* ── Recent calls ── */}
              <Section title={`Recent Calls (last ${detail.calls.items.length} of ${detail.calls.total})`}>
                {detail.calls.items.length === 0 ? (
                  <p className="text-sm text-gray-500 py-4 text-center">
                    No calls in this period.
                  </p>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-[#222222]">
                          <th className="py-2 pr-3 text-left text-xs text-gray-500 font-medium">
                            Time
                          </th>
                          <th className="py-2 pr-3 text-left text-xs text-gray-500 font-medium">
                            Caller
                          </th>
                          <th className="py-2 pr-3 text-left text-xs text-gray-500 font-medium">
                            Duration
                          </th>
                          <th className="py-2 pr-3 text-right text-xs text-gray-500 font-medium">
                            Mins
                          </th>
                          <th className="py-2 pr-3 text-right text-xs text-gray-500 font-medium">
                            Billable
                          </th>
                          <th className="py-2 text-right text-xs text-gray-500 font-medium">
                            Internal
                          </th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[#1a1a1a]">
                        {detail.calls.items.flatMap((call) => {
                          const isExpanded = expandedCalls.has(call.call_log_id);
                          const transferItems = call.billing_items.filter(
                            (i) => i.item_type === "outbound_transfer"
                          );
                          const internalCost = 0;

                          const mainRow = (
                            <tr
                              key={`main-${call.call_log_id}`}
                              className="hover:bg-[#0a0a0a] transition-colors"
                            >
                              <td className="py-2 pr-3 text-gray-400 text-xs whitespace-nowrap">
                                {call.started_at
                                  ? new Date(call.started_at).toLocaleString()
                                  : "—"}
                              </td>
                              <td className="py-2 pr-3 text-gray-300 font-mono text-xs">
                                {call.caller_number ?? "—"}
                              </td>
                              <td className="py-2 pr-3 text-gray-400 text-xs">
                                {fmtDuration(call.duration_seconds)}
                              </td>
                              <td className="py-2 pr-3 text-right text-gray-300 text-xs">
                                {call.billable_inbound_minutes}
                              </td>
                              <td className="py-2 pr-3 text-right text-gray-300 text-xs">
                                ${call.total_cost_usd.toFixed(4)}
                              </td>
                              <td className="py-2 text-right text-xs">
                                {call.has_transfers ? (
                                  <button
                                    onClick={() =>
                                      toggleCall(call.call_log_id)
                                    }
                                    className="inline-flex items-center gap-1 text-blue-400 hover:text-blue-300"
                                  >
                                    {isExpanded ? (
                                      <ChevronDown className="h-3 w-3" />
                                    ) : (
                                      <ChevronRight className="h-3 w-3" />
                                    )}
                                    {transferItems.length}
                                  </button>
                                ) : (
                                  <span className="text-gray-600">—</span>
                                )}
                              </td>
                            </tr>
                          );

                          if (!isExpanded || transferItems.length === 0) {
                            return [mainRow];
                          }

                          const subRows = transferItems.map((item, idx) => (
                            <tr
                              key={`leg-${call.call_log_id}-${idx}`}
                              className="bg-[#0a0a0a]"
                            >
                              <td
                                colSpan={2}
                                className="py-1.5 pl-6 pr-3 text-xs text-gray-500"
                              >
                                <span className="text-gray-600 mr-2">↳</span>
                                {item.destination ?? "Transfer"}
                                {item.leg_type && (
                                  <span className="ml-2 text-gray-600">
                                    ({item.leg_type})
                                  </span>
                                )}
                              </td>
                              <td className="py-1.5 pr-3 text-xs text-gray-500">
                                {item.leg_duration_seconds != null
                                  ? fmtDuration(item.leg_duration_seconds)
                                  : "—"}
                              </td>
                              <td className="py-1.5 pr-3 text-right text-xs text-gray-500">
                                {item.quantity_minutes}
                              </td>
                              <td className="py-1.5 pr-3 text-right text-xs text-gray-500">
                                ${item.cost_usd.toFixed(4)}
                              </td>
                              <td className="py-1.5 text-right text-xs text-gray-600">
                                —
                              </td>
                            </tr>
                          ));

                          return [mainRow, ...subRows];
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </Section>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────────────
// Sub-components
// ──────────────────────────────────────────────────────────────────────────────

function Section({
  title,
  amber,
  children,
}: {
  title: string;
  amber?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div
      className={
        amber
          ? "border border-yellow-600/20 bg-yellow-500/5 rounded-xl p-4"
          : ""
      }
    >
      <h3
        className={`text-sm font-semibold mb-3 ${
          amber ? "text-yellow-400" : "text-white"
        }`}
      >
        {title}
      </h3>
      {children}
    </div>
  );
}

function StatCard({
  label,
  value,
  sub,
  highlight,
  amber,
}: {
  label: string;
  value: string;
  sub?: string;
  highlight?: boolean;
  amber?: boolean;
}) {
  return (
    <div
      className={`rounded-lg p-4 border ${
        highlight
          ? amber
            ? "bg-yellow-500/10 border-yellow-600/30"
            : "bg-blue-600/10 border-blue-600/20"
          : "bg-[#0a0a0a] border-[#1a1a1a]"
      }`}
    >
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p
        className={`text-lg font-semibold ${
          highlight ? (amber ? "text-yellow-300" : "text-blue-300") : "text-white"
        }`}
      >
        {value}
      </p>
      {sub && <p className="text-xs text-gray-600 mt-1">{sub}</p>}
    </div>
  );
}

function RateField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-400 mb-1">
        {label}
      </label>
      <input
        type="number"
        min="0"
        step="0.000001"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full px-3 py-2 bg-[#0a0a0a] border border-[#222222] rounded-lg text-white text-sm focus:outline-none focus:border-blue-600"
      />
    </div>
  );
}
