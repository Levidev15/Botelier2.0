"use client";

import { useSession } from "next-auth/react";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Building2,
  Plus,
  Search,
  MoreVertical,
  Phone,
  Users,
  ExternalLink,
} from "lucide-react";
import { toast } from "sonner";
import { useAuthToken } from "@/lib/auth/useAuthToken";

interface Account {
  id: string;
  name: string;
  slug: string;
  email: string;
  phone: string | null;
  business_type: string | null;
  status: string;
  subscription_tier: string;
  has_twilio: boolean;
  twilio_sub_account_sid: string | null;
  member_count: number;
  created_at: string;
}

interface AccountListResponse {
  accounts: Account[];
  total: number;
  page: number;
  page_size: number;
}

export default function AccountsPage() {
  const { data: session } = useSession();
  const { token, authFetch } = useAuthToken();
  const router = useRouter();
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newAccount, setNewAccount] = useState({
    name: "",
    email: "",
    phone: "",
    business_type: "",
    subscription_tier: "free",
    provision_twilio: false,
  });

  useEffect(() => {
    if (session && token) {
      fetchAccounts();
    }
  }, [session, token, page, statusFilter]);

  const fetchAccounts = async () => {
    if (!token) return;
    try {
      setLoading(true);
      const params = new URLSearchParams({
        page: page.toString(),
        page_size: "20",
      });
      if (statusFilter) params.set("status", statusFilter);
      if (search) params.set("search", search);

      const res = await authFetch(`/api/admin/accounts?${params}`);
      if (res.ok) {
        const data: AccountListResponse = await res.json();
        setAccounts(data.accounts);
        setTotal(data.total);
      }
    } catch (err) {
      console.error("Error fetching accounts:", err);
      toast.error("Failed to load accounts");
    } finally {
      setLoading(false);
    }
  };

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    fetchAccounts();
  };

  const handleCreateAccount = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newAccount.name.trim() || !newAccount.email.trim()) {
      toast.error("Name and email are required");
      return;
    }

    setCreating(true);
    try {
      const params = new URLSearchParams();
      if (newAccount.provision_twilio) {
        params.set("provision_twilio", "true");
      }

      const res = await authFetch(`/api/admin/accounts?${params}`, {
        method: "POST",
        body: JSON.stringify({
          name: newAccount.name,
          email: newAccount.email,
          phone: newAccount.phone || null,
          business_type: newAccount.business_type || null,
          subscription_tier: newAccount.subscription_tier,
        }),
      });

      if (res.ok) {
        toast.success("Account created successfully");
        setShowCreateModal(false);
        setNewAccount({
          name: "",
          email: "",
          phone: "",
          business_type: "",
          subscription_tier: "free",
          provision_twilio: false,
        });
        fetchAccounts();
      } else {
        const error = await res.json();
        toast.error(error.detail || "Failed to create account");
      }
    } catch (err) {
      console.error("Error creating account:", err);
      toast.error("Failed to create account");
    } finally {
      setCreating(false);
    }
  };

  const handleProvisionTwilio = async (accountId: string) => {
    if (!token) return;
    try {
      const res = await authFetch(`/api/admin/accounts/${accountId}/provision-twilio`, {
        method: "POST",
      });

      if (res.ok) {
        toast.success("Twilio sub-account provisioned");
        fetchAccounts();
      } else {
        const error = await res.json();
        toast.error(error.detail || "Failed to provision Twilio");
      }
    } catch (err) {
      console.error("Error provisioning Twilio:", err);
      toast.error("Failed to provision Twilio");
    }
  };

  const statusColors: Record<string, string> = {
    trial: "bg-yellow-600/20 text-yellow-400",
    active: "bg-green-600/20 text-green-400",
    suspended: "bg-red-600/20 text-red-400",
    cancelled: "bg-gray-600/20 text-gray-400",
  };

  const tierLabels: Record<string, string> = {
    free: "Free",
    starter: "Starter",
    professional: "Professional",
    enterprise: "Enterprise",
  };

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-white">Accounts</h1>
          <p className="text-gray-400 mt-1">
            Manage all accounts on the platform
          </p>
        </div>
        <button
          onClick={() => setShowCreateModal(true)}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors"
        >
          <Plus className="h-4 w-4" />
          Create Account
        </button>
      </div>

      <div className="mb-6 flex flex-wrap gap-4">
        <form onSubmit={handleSearch} className="flex-1 min-w-[300px]">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-500" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search accounts..."
              className="w-full pl-10 pr-4 py-2 bg-[#111111] border border-[#222222] rounded-lg text-white placeholder-gray-500 focus:outline-none focus:border-blue-600"
            />
          </div>
        </form>

        <select
          value={statusFilter}
          onChange={(e) => {
            setStatusFilter(e.target.value);
            setPage(1);
          }}
          className="px-4 py-2 bg-[#111111] border border-[#222222] rounded-lg text-white focus:outline-none focus:border-blue-600"
        >
          <option value="">All Statuses</option>
          <option value="trial">Trial</option>
          <option value="active">Active</option>
          <option value="suspended">Suspended</option>
          <option value="cancelled">Cancelled</option>
        </select>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-12">
          <div className="animate-spin h-8 w-8 border-4 border-blue-600 border-t-transparent rounded-full"></div>
        </div>
      ) : accounts.length === 0 ? (
        <div className="bg-[#111111] border border-[#222222] rounded-xl p-12 text-center">
          <Building2 className="h-12 w-12 text-gray-600 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-white mb-2">No accounts found</h3>
          <p className="text-gray-400">
            {search || statusFilter
              ? "Try adjusting your filters"
              : "Create your first account to get started"}
          </p>
        </div>
      ) : (
        <>
          <div className="bg-[#111111] border border-[#222222] rounded-xl overflow-hidden">
            <table className="w-full">
              <thead className="bg-[#0a0a0a] border-b border-[#222222]">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                    Account
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                    Status
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                    Tier
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                    Twilio
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                    Members
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                    Created
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-400 uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#222222]">
                {accounts.map((account) => (
                  <tr key={account.id} className="hover:bg-[#1a1a1a]">
                    <td className="px-6 py-4">
                      <div>
                        <p className="text-white font-medium">{account.name}</p>
                        <p className="text-gray-500 text-sm">{account.email}</p>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <span
                        className={`inline-flex px-2 py-1 text-xs font-medium rounded-full ${
                          statusColors[account.status] || statusColors.cancelled
                        }`}
                      >
                        {account.status}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-gray-300">
                      {tierLabels[account.subscription_tier] ||
                        account.subscription_tier}
                    </td>
                    <td className="px-6 py-4">
                      {account.has_twilio ? (
                        <span className="inline-flex items-center gap-1 text-green-400 text-sm">
                          <Phone className="h-4 w-4" />
                          Configured
                        </span>
                      ) : (
                        <button
                          onClick={() => handleProvisionTwilio(account.id)}
                          className="text-sm text-blue-400 hover:text-blue-300"
                        >
                          Provision
                        </button>
                      )}
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-1 text-gray-300">
                        <Users className="h-4 w-4" />
                        {account.member_count}
                      </div>
                    </td>
                    <td className="px-6 py-4 text-gray-400 text-sm">
                      {new Date(account.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-6 py-4 text-right">
                      <button
                        onClick={() =>
                          router.push(`/admin/accounts/${account.id}`)
                        }
                        className="text-gray-400 hover:text-white p-2"
                      >
                        <ExternalLink className="h-4 w-4" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {total > 20 && (
            <div className="mt-4 flex items-center justify-between">
              <p className="text-gray-400 text-sm">
                Showing {(page - 1) * 20 + 1} to {Math.min(page * 20, total)} of{" "}
                {total} accounts
              </p>
              <div className="flex gap-2">
                <button
                  onClick={() => setPage(page - 1)}
                  disabled={page === 1}
                  className="px-3 py-1 bg-[#111111] border border-[#222222] rounded text-gray-400 disabled:opacity-50"
                >
                  Previous
                </button>
                <button
                  onClick={() => setPage(page + 1)}
                  disabled={page * 20 >= total}
                  className="px-3 py-1 bg-[#111111] border border-[#222222] rounded text-gray-400 disabled:opacity-50"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </>
      )}

      {showCreateModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-[#111111] border border-[#222222] rounded-xl p-6 max-w-md w-full mx-4">
            <h2 className="text-xl font-semibold text-white mb-6">
              Create New Account
            </h2>
            <form onSubmit={handleCreateAccount} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-400 mb-1">
                  Account Name *
                </label>
                <input
                  type="text"
                  value={newAccount.name}
                  onChange={(e) =>
                    setNewAccount({ ...newAccount, name: e.target.value })
                  }
                  className="w-full px-4 py-2 bg-[#0a0a0a] border border-[#222222] rounded-lg text-white focus:outline-none focus:border-blue-600"
                  placeholder="Acme Corporation"
                  required
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-400 mb-1">
                  Email *
                </label>
                <input
                  type="email"
                  value={newAccount.email}
                  onChange={(e) =>
                    setNewAccount({ ...newAccount, email: e.target.value })
                  }
                  className="w-full px-4 py-2 bg-[#0a0a0a] border border-[#222222] rounded-lg text-white focus:outline-none focus:border-blue-600"
                  placeholder="admin@acme.com"
                  required
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-400 mb-1">
                  Phone
                </label>
                <input
                  type="tel"
                  value={newAccount.phone}
                  onChange={(e) =>
                    setNewAccount({ ...newAccount, phone: e.target.value })
                  }
                  className="w-full px-4 py-2 bg-[#0a0a0a] border border-[#222222] rounded-lg text-white focus:outline-none focus:border-blue-600"
                  placeholder="+1 (555) 123-4567"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-400 mb-1">
                  Business Type
                </label>
                <input
                  type="text"
                  value={newAccount.business_type}
                  onChange={(e) =>
                    setNewAccount({
                      ...newAccount,
                      business_type: e.target.value,
                    })
                  }
                  className="w-full px-4 py-2 bg-[#0a0a0a] border border-[#222222] rounded-lg text-white focus:outline-none focus:border-blue-600"
                  placeholder="Hotel, Healthcare, Restaurant..."
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-400 mb-1">
                  Subscription Tier
                </label>
                <select
                  value={newAccount.subscription_tier}
                  onChange={(e) =>
                    setNewAccount({
                      ...newAccount,
                      subscription_tier: e.target.value,
                    })
                  }
                  className="w-full px-4 py-2 bg-[#0a0a0a] border border-[#222222] rounded-lg text-white focus:outline-none focus:border-blue-600"
                >
                  <option value="free">Free</option>
                  <option value="starter">Starter</option>
                  <option value="professional">Professional</option>
                  <option value="enterprise">Enterprise</option>
                </select>
              </div>

              <div className="flex items-center gap-3">
                <input
                  type="checkbox"
                  id="provision_twilio"
                  checked={newAccount.provision_twilio}
                  onChange={(e) =>
                    setNewAccount({
                      ...newAccount,
                      provision_twilio: e.target.checked,
                    })
                  }
                  className="w-4 h-4 bg-[#0a0a0a] border border-[#222222] rounded text-blue-600 focus:ring-blue-600"
                />
                <label
                  htmlFor="provision_twilio"
                  className="text-sm text-gray-400"
                >
                  Provision Twilio sub-account automatically
                </label>
              </div>

              <div className="flex gap-3 pt-4">
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  className="flex-1 px-4 py-2 bg-[#1a1a1a] text-gray-300 rounded-lg hover:bg-[#222222] transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creating}
                  className="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-600/50 text-white rounded-lg transition-colors"
                >
                  {creating ? "Creating..." : "Create Account"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
