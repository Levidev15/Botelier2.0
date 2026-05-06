"use client";

import { useEffect, useState, useMemo, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  Search,
  ChevronUp,
  ChevronDown,
  FileDown,
  Loader2,
  RefreshCw,
  BarChart3,
} from "lucide-react";
import { toast } from "sonner";
import { useAuthToken } from "@/lib/auth/useAuthToken";
import BillingSlideOver from "@/components/billing/BillingSlideOver";

// ──────────────────────────────────────────────────────────────────────────────
// Types
// ──────────────────────────────────────────────────────────────────────────────

type PeriodKey = "mtd" | "7d" | "30d";

interface AccountUsageRow {
  account_id: string;
  account_name: string;
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
  internal_cost_usd: number;
  margin_usd: number;
  // Merged from accounts API
  status?: string;
}

interface UsageListResponse {
  period_start: string;
  period_end: string;
  accounts: AccountUsageRow[];
  total_accounts: number;
}

interface AccountInfo {
  id: string;
  status: string;
}

type SortField =
  | "account_name"
  | "status"
  | "inbound_minutes"
  | "outbound_minutes"
  | "sms_total"
  | "billable_total_usd"
  | "internal_cost_usd"
  | "margin_usd";

// ──────────────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────────────

const PERIOD_LABELS: Record<PeriodKey, string> = {
  mtd: "Month to Date",
  "7d": "Last 7 Days",
  "30d": "Last 30 Days",
};

const STATUS_COLORS: Record<string, string> = {
  trial: "bg-yellow-600/20 text-yellow-400 border-yellow-600/30",
  active: "bg-green-600/20 text-green-400 border-green-600/30",
  suspended: "bg-red-600/20 text-red-400 border-red-600/30",
  cancelled: "bg-gray-600/20 text-gray-400 border-gray-600/30",
};

function fmt$(n: number) {
  return `$${n.toFixed(4)}`;
}

function SortIcon({
  field,
  active,
  dir,
}: {
  field: string;
  active: boolean;
  dir: "asc" | "desc";
}) {
  if (!active)
    return <ChevronDown className="h-3 w-3 text-gray-600 inline ml-1" />;
  return dir === "asc" ? (
    <ChevronUp className="h-3 w-3 text-blue-400 inline ml-1" />
  ) : (
    <ChevronDown className="h-3 w-3 text-blue-400 inline ml-1" />
  );
}

// ──────────────────────────────────────────────────────────────────────────────
// Page
// ──────────────────────────────────────────────────────────────────────────────

export default function AdminUsagePage() {
  const { token, user, loading: authLoading, authFetch } = useAuthToken();
  const router = useRouter();

  const [period, setPeriod] = useState<PeriodKey>("mtd");
  const [rows, setRows] = useState<AccountUsageRow[]>([]);
  const [periodStart, setPeriodStart] = useState<string>("");
  const [periodEnd, setPeriodEnd] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [sortField, setSortField] = useState<SortField>("billable_total_usd");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [billingAccountId, setBillingAccountId] = useState<string | null>(null);

  // Auth guard
  useEffect(() => {
    if (authLoading) return;
    if (!token) {
      router.push("/login?callbackUrl=/admin/usage");
      return;
    }
    if (user?.user_type !== "platform_admin") {
      router.push("/dashboard");
    }
  }, [token, user, authLoading, router]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [billingRes, accountsRes] = await Promise.all([
        authFetch(`/api/admin/billing/accounts?period=${period}&sort_by=total_cost&order=desc`),
        authFetch(`/api/admin/accounts?page_size=500`),
      ]);

      if (!billingRes.ok) {
        const err = await billingRes.json().catch(() => ({}));
        toast.error(err.detail || "Failed to load usage data");
        return;
      }

      const billing: UsageListResponse = await billingRes.json();
      setPeriodStart(billing.period_start);
      setPeriodEnd(billing.period_end);

      let statusMap: Record<string, string> = {};
      if (accountsRes.ok) {
        const acctData = await accountsRes.json();
        for (const a of acctData.accounts ?? []) {
          statusMap[a.id] = a.status;
        }
      }

      const merged = billing.accounts.map((row) => ({
        ...row,
        status: statusMap[row.account_id] ?? "unknown",
      }));
      setRows(merged);
    } catch (e) {
      toast.error("Failed to load usage data");
    } finally {
      setLoading(false);
    }
  }, [period, authFetch]);

  useEffect(() => {
    if (!authLoading && token && user?.user_type === "platform_admin") {
      fetchData();
    }
  }, [period, authLoading, token, user, fetchData]);

  // Client-side filter + sort
  const filtered = useMemo(() => {
    let result = rows;
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      result = result.filter((r) =>
        r.account_name.toLowerCase().includes(q)
      );
    }
    return [...result].sort((a, b) => {
      let va: number | string;
      let vb: number | string;
      switch (sortField) {
        case "account_name":
          va = a.account_name.toLowerCase();
          vb = b.account_name.toLowerCase();
          break;
        case "status":
          va = a.status ?? "";
          vb = b.status ?? "";
          break;
        case "inbound_minutes":
          va = a.inbound_minutes;
          vb = b.inbound_minutes;
          break;
        case "outbound_minutes":
          va = a.outbound_minutes;
          vb = b.outbound_minutes;
          break;
        case "sms_total":
          va = a.sms_inbound_count + a.sms_outbound_count;
          vb = b.sms_inbound_count + b.sms_outbound_count;
          break;
        case "billable_total_usd":
          va = a.billable_total_usd;
          vb = b.billable_total_usd;
          break;
        case "internal_cost_usd":
          va = a.internal_cost_usd;
          vb = b.internal_cost_usd;
          break;
        case "margin_usd":
          va = a.margin_usd;
          vb = b.margin_usd;
          break;
        default:
          va = 0;
          vb = 0;
      }
      if (typeof va === "string") {
        return sortDir === "asc"
          ? va.localeCompare(vb as string)
          : (vb as string).localeCompare(va);
      }
      return sortDir === "asc"
        ? (va as number) - (vb as number)
        : (vb as number) - (va as number);
    });
  }, [rows, search, sortField, sortDir]);

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortField(field);
      setSortDir("desc");
    }
  };

  const handleExportCSV = () => {
    const headers = [
      "Account",
      "Status",
      "Inbound Mins",
      "Outbound Mins",
      "SMS Total",
      "Billable ($)",
      "Internal Cost ($)",
      "Margin ($)",
    ];
    const csvRows = filtered.map((r) => [
      `"${r.account_name.replace(/"/g, '""')}"`,
      r.status ?? "",
      r.inbound_minutes,
      r.outbound_minutes,
      r.sms_inbound_count + r.sms_outbound_count,
      r.billable_total_usd.toFixed(6),
      r.internal_cost_usd.toFixed(6),
      r.margin_usd.toFixed(6),
    ]);
    const csv = [headers.join(","), ...csvRows.map((r) => r.join(","))].join(
      "\n"
    );
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `botelier-usage-${period}-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  if (authLoading) {
    return (
      <div className="min-h-screen bg-[#0a0a0a] flex items-center justify-center">
        <div className="animate-spin h-8 w-8 border-4 border-blue-600 border-t-transparent rounded-full" />
      </div>
    );
  }

  const colHeader = (label: string, field: SortField) => (
    <th
      className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider cursor-pointer select-none hover:text-white transition-colors"
      onClick={() => handleSort(field)}
    >
      {label}
      <SortIcon field={field} active={sortField === field} dir={sortDir} />
    </th>
  );

  return (
    <div className="p-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-white">Platform Usage</h1>
          <p className="text-gray-400 mt-1">
            Cross-account usage &amp; cost breakdown
            {periodStart && (
              <span className="ml-2 text-gray-600 text-xs">
                {new Date(periodStart).toLocaleDateString()} –{" "}
                {new Date(periodEnd).toLocaleDateString()}
              </span>
            )}
          </p>
        </div>

        <div className="flex items-center gap-3">
          {/* Period picker */}
          <div className="flex rounded-lg border border-[#222222] overflow-hidden">
            {(Object.keys(PERIOD_LABELS) as PeriodKey[]).map((p) => (
              <button
                key={p}
                onClick={() => setPeriod(p)}
                className={`px-3 py-1.5 text-sm transition-colors ${
                  period === p
                    ? "bg-blue-600 text-white"
                    : "bg-[#111111] text-gray-400 hover:text-white"
                }`}
              >
                {PERIOD_LABELS[p]}
              </button>
            ))}
          </div>

          <button
            onClick={fetchData}
            disabled={loading}
            className="p-2 text-gray-400 hover:text-white hover:bg-[#1a1a1a] rounded-lg transition-colors"
            title="Refresh"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          </button>

          <button
            onClick={handleExportCSV}
            disabled={filtered.length === 0}
            className="flex items-center gap-2 px-3 py-2 bg-[#1a1a1a] hover:bg-[#222222] disabled:opacity-40 text-gray-300 rounded-lg transition-colors text-sm"
          >
            <FileDown className="h-4 w-4" />
            Export CSV
          </button>
        </div>
      </div>

      {/* Search */}
      <div className="mb-4 relative w-80">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-500" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search accounts..."
          className="w-full pl-10 pr-4 py-2 bg-[#111111] border border-[#222222] rounded-lg text-white placeholder-gray-500 focus:outline-none focus:border-blue-600 text-sm"
        />
      </div>

      {/* Table */}
      {loading ? (
        <div className="flex items-center justify-center py-24">
          <Loader2 className="h-8 w-8 text-blue-600 animate-spin" />
        </div>
      ) : filtered.length === 0 ? (
        <div className="bg-[#111111] border border-[#222222] rounded-xl p-12 text-center">
          <BarChart3 className="h-12 w-12 text-gray-600 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-white mb-2">No data found</h3>
          <p className="text-gray-400">
            {search ? "Try a different search term." : "No usage data for this period."}
          </p>
        </div>
      ) : (
        <div className="bg-[#111111] border border-[#222222] rounded-xl overflow-hidden">
          <table className="w-full">
            <thead className="bg-[#0a0a0a] border-b border-[#222222]">
              <tr>
                {colHeader("Account", "account_name")}
                {colHeader("Status", "status")}
                {colHeader("Inbound Mins", "inbound_minutes")}
                {colHeader("Outbound Mins", "outbound_minutes")}
                {colHeader("SMS", "sms_total")}
                {colHeader("Billable", "billable_total_usd")}
                {colHeader("Internal Cost", "internal_cost_usd")}
                {colHeader("Margin", "margin_usd")}
              </tr>
            </thead>
            <tbody className="divide-y divide-[#1a1a1a]">
              {filtered.map((row) => {
                const margin = row.margin_usd;
                const marginColor =
                  margin >= 0 ? "text-green-400" : "text-red-400";

                return (
                  <tr
                    key={row.account_id}
                    className="hover:bg-[#1a1a1a] transition-colors"
                  >
                    <td className="px-4 py-3">
                      <button
                        onClick={() => setBillingAccountId(row.account_id)}
                        className="text-blue-400 hover:text-blue-300 font-medium text-sm transition-colors text-left"
                      >
                        {row.account_name}
                      </button>
                    </td>
                    <td className="px-4 py-3">
                      {row.status && row.status !== "unknown" ? (
                        <span
                          className={`inline-flex px-2 py-0.5 text-xs font-medium rounded-full border ${
                            STATUS_COLORS[row.status] ?? STATUS_COLORS.cancelled
                          }`}
                        >
                          {row.status.charAt(0).toUpperCase() +
                            row.status.slice(1)}
                        </span>
                      ) : (
                        <span className="text-gray-600 text-xs">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-300">
                      {row.inbound_minutes.toLocaleString()}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-300">
                      {row.outbound_minutes.toLocaleString()}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-300">
                      {(
                        row.sms_inbound_count + row.sms_outbound_count
                      ).toLocaleString()}
                    </td>
                    <td className="px-4 py-3 text-sm text-white font-medium">
                      {fmt$(row.billable_total_usd)}
                    </td>
                    <td className="px-4 py-3 text-sm text-yellow-400">
                      {fmt$(row.internal_cost_usd)}
                    </td>
                    <td className={`px-4 py-3 text-sm font-medium ${marginColor}`}>
                      {fmt$(margin)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          <div className="px-4 py-3 border-t border-[#222222] text-xs text-gray-500">
            Showing {filtered.length} of {rows.length} accounts
          </div>
        </div>
      )}

      {/* Billing slide-over */}
      <BillingSlideOver
        accountId={billingAccountId}
        onClose={() => setBillingAccountId(null)}
        period={period}
      />
    </div>
  );
}
