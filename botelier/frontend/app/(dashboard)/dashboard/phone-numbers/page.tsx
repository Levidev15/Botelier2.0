"use client";

import { useState, useEffect } from "react";
import { Plus, Phone } from "lucide-react";
import PhoneNumberCard from "./components/PhoneNumberCard";
import AddNumberDrawer from "./components/AddNumberDrawer";

interface PhoneNumber {
  id: string;
  phone_number: string;
  friendly_name: string | null;
  country_code: string;
  assistant_id: string | null;
  hotel_id: string;
  is_active: boolean;
  created_at: string;
}

interface Assistant {
  id: string;
  name: string;
}

export default function PhoneNumbersPage() {
  const [phoneNumbers, setPhoneNumbers] = useState<PhoneNumber[]>([]);
  const [assistants, setAssistants] = useState<Assistant[]>([]);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [loading, setLoading] = useState(true);

  const fetchPhoneNumbers = async () => {
    try {
      setLoading(true);
      // TODO: Replace with actual hotel_id from auth context when available
      const response = await fetch(`/api/phone-numbers`);
      const data = await response.json();
      setPhoneNumbers(data.phone_numbers || []);
    } catch (error) {
      console.error("Failed to fetch phone numbers:", error);
      setPhoneNumbers([]);
    } finally {
      setLoading(false);
    }
  };

  const fetchAssistants = async (hotelId: string) => {
    try {
      const response = await fetch(`/api/assistants?hotel_id=${hotelId}`);
      const data = await response.json();
      setAssistants(data.assistants || []);
    } catch (error) {
      console.error("Failed to fetch assistants:", error);
      setAssistants([]);
    }
  };

  useEffect(() => {
    fetchPhoneNumbers();
    // Fetch assistants on mount - using Demo Hotel ID until auth is implemented
    const hotelId = "6b410bcc-f843-40df-b32d-078d3e01ac7f";
    fetchAssistants(hotelId);
  }, []);

  const handleNumberAdded = () => {
    setIsDrawerOpen(false);
    fetchPhoneNumbers();
  };

  const handleDelete = async (id: string) => {
    if (!confirm("Are you sure you want to release this phone number?")) return;

    try {
      const response = await fetch(`/api/phone-numbers/${id}`, {
        method: "DELETE",
      });

      if (response.ok) {
        fetchPhoneNumbers();
      } else {
        alert("Failed to delete phone number");
      }
    } catch (error) {
      console.error("Failed to delete phone number:", error);
      alert("Failed to delete phone number");
    }
  };

  return (
    <div className="flex-1 overflow-auto bg-[#0a0a0a]">
      <div className="max-w-7xl mx-auto px-6 py-8">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-3xl font-bold text-white mb-2">Phone Numbers</h1>
            <p className="text-gray-400">Manage your Twilio phone numbers</p>
          </div>
          <button
            onClick={() => setIsDrawerOpen(true)}
            className="flex items-center space-x-2 bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg transition-colors"
          >
            <Plus className="h-5 w-5" />
            <span>Add Number</span>
          </button>
        </div>

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
            <button
              onClick={() => setIsDrawerOpen(true)}
              className="flex items-center space-x-2 bg-blue-600 hover:bg-blue-700 text-white px-6 py-3 rounded-lg transition-colors"
            >
              <Plus className="h-5 w-5" />
              <span>Add Your First Number</span>
            </button>
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
