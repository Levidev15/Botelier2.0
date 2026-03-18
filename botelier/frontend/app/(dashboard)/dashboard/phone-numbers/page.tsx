"use client";

import { useState, useEffect } from "react";
import { Plus, Phone } from "lucide-react";
import PhoneNumberCard from "./components/PhoneNumberCard";
import AddNumberDrawer from "./components/AddNumberDrawer";
import { notify, confirmAction } from "@/lib/notifications";
import { useAccountContext } from "@/lib/auth/useAccountContext";
import { usePagePermission, PermissionGate, AccessDeniedPage } from "@/components/ui/PermissionGate";
import { usePermissions } from "@/lib/auth/usePermissions";

interface PhoneNumber {
  id: string;
  phone_number: string;
  friendly_name: string | null;
  country_code: string;
  assistant_id: string | null;
  hotel_id: string;
  is_active: boolean;
  created_at: string;
  sms_enabled?: boolean;
  sms_assistant_id?: string | null;
}

interface Assistant {
  id: string;
  name: string;
}

export default function PhoneNumbersPage() {
  const { accountId, loading: contextLoading } = useAccountContext();
  const { hasAccess, loading: permLoading } = usePagePermission("phone_numbers", "view");
  const { can, isPlatformAdmin } = usePermissions();
  const canPurchase = isPlatformAdmin || can("phone_numbers", "purchase");
  const canConfigure = isPlatformAdmin || can("phone_numbers", "configure");
  const canRelease = isPlatformAdmin || can("phone_numbers", "release");
  const [phoneNumbers, setPhoneNumbers] = useState<PhoneNumber[]>([]);
  const [assistants, setAssistants] = useState<Assistant[]>([]);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [loading, setLoading] = useState(true);

  const fetchPhoneNumbers = async () => {
    if (!accountId) return;
    try {
      setLoading(true);
      const response = await fetch(`/api/phone-numbers?hotel_id=${accountId}`);
      const data = await response.json();
      setPhoneNumbers(data.phone_numbers || []);
    } catch (error) {
      console.error("Failed to fetch phone numbers:", error);
      setPhoneNumbers([]);
    } finally {
      setLoading(false);
    }
  };

  const fetchAssistants = async () => {
    if (!accountId) return;
    try {
      const response = await fetch(`/api/assistants?hotel_id=${accountId}`);
      const data = await response.json();
      setAssistants(data.assistants || []);
    } catch (error) {
      console.error("Failed to fetch assistants:", error);
      setAssistants([]);
    }
  };

  useEffect(() => {
    if (!contextLoading && accountId) {
      fetchPhoneNumbers();
      fetchAssistants();
    }
  }, [accountId, contextLoading]);

  const handleNumberAdded = () => {
    setIsDrawerOpen(false);
    fetchPhoneNumbers();
  };

  const handleDelete = async (id: string) => {
    const confirmed = await confirmAction("Are you sure you want to release this phone number?", {
      confirmText: "Release",
      cancelText: "Cancel",
    });
    if (!confirmed) return;

    try {
      const response = await fetch(`/api/phone-numbers/${id}`, {
        method: "DELETE",
      });

      if (response.ok) {
        notify.success("Phone number released successfully");
        fetchPhoneNumbers();
      } else {
        notify.error("Failed to delete phone number");
      }
    } catch (error) {
      console.error("Failed to delete phone number:", error);
      notify.error("Failed to delete phone number");
    }
  };

  if (!permLoading && !hasAccess) {
    return <AccessDeniedPage message="You don't have permission to view phone numbers." />;
  }

  return (
    <div className="h-full">
      <div className="border-b border-gray-800 bg-[#0a0a0a] sticky top-0 z-10">
        <div className="px-8 py-6">
          <div className="flex justify-between items-center">
            <div>
              <h1 className="text-2xl font-bold">Phone Numbers</h1>
              <p className="text-sm text-gray-400 mt-1">
                Manage your Twilio phone numbers
              </p>
            </div>
            {canPurchase && (
              <button
                onClick={() => setIsDrawerOpen(true)}
                className="inline-flex items-center px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg transition text-sm font-medium"
              >
                <Plus className="h-4 w-4 mr-2" />
                Add Number
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="p-8">
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <div className="text-gray-400">Loading phone numbers...</div>
          </div>
        ) : phoneNumbers.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16">
            <div className="w-20 h-20 bg-gray-800 rounded-full flex items-center justify-center mb-4">
              <Phone className="h-10 w-10 text-gray-600" />
            </div>
            <h2 className="text-xl font-semibold text-white mb-2">No phone numbers yet</h2>
            <p className="text-gray-400 text-center mb-6 max-w-md">
              Add a phone number to start receiving calls
            </p>
            {canPurchase && (
              <button
                onClick={() => setIsDrawerOpen(true)}
                className="flex items-center space-x-2 bg-blue-600 hover:bg-blue-700 text-white px-6 py-3 rounded-lg transition-colors"
              >
                <Plus className="h-5 w-5" />
                <span>Add Your First Number</span>
              </button>
            )}
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {phoneNumbers.map((number) => (
              <PhoneNumberCard
                key={number.id}
                phoneNumber={number}
                assistants={assistants}
                onDelete={handleDelete}
                onUpdate={fetchPhoneNumbers}
                canConfigure={canConfigure}
                canRelease={canRelease}
              />
            ))}
          </div>
        )}
      </div>

      <AddNumberDrawer
        isOpen={isDrawerOpen}
        onClose={() => setIsDrawerOpen(false)}
        onNumberAdded={handleNumberAdded}
      />
    </div>
  );
}
