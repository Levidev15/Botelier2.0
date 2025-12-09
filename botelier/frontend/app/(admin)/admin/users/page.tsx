"use client";

import { useSession } from "next-auth/react";
import { useEffect, useState } from "react";
import { Users, Search, Shield, User as UserIcon } from "lucide-react";
import { toast } from "sonner";
import { useAuthToken } from "@/lib/auth/useAuthToken";

interface User {
  id: string;
  replit_id: string;
  email: string | null;
  first_name: string | null;
  last_name: string | null;
  profile_image_url: string | null;
  user_type: string;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export default function UsersPage() {
  const { data: session } = useSession();
  const { token, authFetch } = useAuthToken();
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("");

  useEffect(() => {
    if (session && token) {
      fetchUsers();
    }
  }, [session, token, typeFilter]);

  const fetchUsers = async () => {
    if (!token) return;
    try {
      setLoading(true);
      const params = new URLSearchParams();
      if (typeFilter) params.set("user_type", typeFilter);
      if (search) params.set("search", search);

      const res = await authFetch(`/api/admin/users?${params}`);
      if (res.ok) {
        setUsers(await res.json());
      }
    } catch (err) {
      console.error("Error fetching users:", err);
      toast.error("Failed to load users");
    } finally {
      setLoading(false);
    }
  };

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    fetchUsers();
  };

  const handleTogglePlatformAdmin = async (user: User) => {
    if (!token) return;
    const endpoint =
      user.user_type === "platform_admin"
        ? `/api/admin/users/${user.id}/remove-platform-admin`
        : `/api/admin/users/${user.id}/make-platform-admin`;

    try {
      const res = await authFetch(endpoint, {
        method: "POST",
      });

      if (res.ok) {
        toast.success(
          user.user_type === "platform_admin"
            ? "Removed platform admin access"
            : "Granted platform admin access"
        );
        fetchUsers();
      } else {
        const error = await res.json();
        toast.error(error.detail || "Failed to update user");
      }
    } catch (err) {
      console.error("Error updating user:", err);
      toast.error("Failed to update user");
    }
  };

  const getDisplayName = (user: User) => {
    if (user.first_name && user.last_name) {
      return `${user.first_name} ${user.last_name}`;
    }
    if (user.first_name) return user.first_name;
    if (user.email) return user.email.split("@")[0];
    return `User ${user.id.slice(0, 8)}`;
  };

  return (
    <div className="p-8">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-white">Users</h1>
        <p className="text-gray-400 mt-1">
          Manage all users on the platform
        </p>
      </div>

      <div className="mb-6 flex flex-wrap gap-4">
        <form onSubmit={handleSearch} className="flex-1 min-w-[300px]">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-500" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search users..."
              className="w-full pl-10 pr-4 py-2 bg-[#111111] border border-[#222222] rounded-lg text-white placeholder-gray-500 focus:outline-none focus:border-blue-600"
            />
          </div>
        </form>

        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          className="px-4 py-2 bg-[#111111] border border-[#222222] rounded-lg text-white focus:outline-none focus:border-blue-600"
        >
          <option value="">All Users</option>
          <option value="platform_admin">Platform Admins</option>
          <option value="account_user">Account Users</option>
        </select>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-12">
          <div className="animate-spin h-8 w-8 border-4 border-blue-600 border-t-transparent rounded-full"></div>
        </div>
      ) : users.length === 0 ? (
        <div className="bg-[#111111] border border-[#222222] rounded-xl p-12 text-center">
          <Users className="h-12 w-12 text-gray-600 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-white mb-2">No users found</h3>
          <p className="text-gray-400">
            {search || typeFilter
              ? "Try adjusting your filters"
              : "Users will appear here once they sign up"}
          </p>
        </div>
      ) : (
        <div className="bg-[#111111] border border-[#222222] rounded-xl overflow-hidden">
          <table className="w-full">
            <thead className="bg-[#0a0a0a] border-b border-[#222222]">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                  User
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                  Type
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                  Status
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                  Last Login
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                  Joined
                </th>
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-400 uppercase tracking-wider">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#222222]">
              {users.map((user) => (
                <tr key={user.id} className="hover:bg-[#1a1a1a]">
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-3">
                      {user.profile_image_url ? (
                        <img
                          src={user.profile_image_url}
                          alt=""
                          className="h-10 w-10 rounded-full object-cover"
                        />
                      ) : (
                        <div className="h-10 w-10 rounded-full bg-blue-600/20 flex items-center justify-center">
                          <UserIcon className="h-5 w-5 text-blue-400" />
                        </div>
                      )}
                      <div>
                        <p className="text-white font-medium">
                          {getDisplayName(user)}
                        </p>
                        <p className="text-gray-500 text-sm">
                          {user.email || "No email"}
                        </p>
                      </div>
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    {user.user_type === "platform_admin" ? (
                      <span className="inline-flex items-center gap-1 px-2 py-1 bg-purple-600/20 text-purple-400 text-xs font-medium rounded-full">
                        <Shield className="h-3 w-3" />
                        Platform Admin
                      </span>
                    ) : (
                      <span className="inline-flex px-2 py-1 bg-gray-600/20 text-gray-400 text-xs font-medium rounded-full">
                        Account User
                      </span>
                    )}
                  </td>
                  <td className="px-6 py-4">
                    <span
                      className={`inline-flex px-2 py-1 text-xs font-medium rounded-full ${
                        user.is_active
                          ? "bg-green-600/20 text-green-400"
                          : "bg-red-600/20 text-red-400"
                      }`}
                    >
                      {user.is_active ? "Active" : "Disabled"}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-gray-400 text-sm">
                    {user.last_login_at
                      ? new Date(user.last_login_at).toLocaleDateString()
                      : "Never"}
                  </td>
                  <td className="px-6 py-4 text-gray-400 text-sm">
                    {new Date(user.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-6 py-4 text-right">
                    <button
                      onClick={() => handleTogglePlatformAdmin(user)}
                      className={`text-sm px-3 py-1 rounded transition-colors ${
                        user.user_type === "platform_admin"
                          ? "text-red-400 hover:bg-red-900/20"
                          : "text-blue-400 hover:bg-blue-900/20"
                      }`}
                    >
                      {user.user_type === "platform_admin"
                        ? "Remove Admin"
                        : "Make Admin"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
