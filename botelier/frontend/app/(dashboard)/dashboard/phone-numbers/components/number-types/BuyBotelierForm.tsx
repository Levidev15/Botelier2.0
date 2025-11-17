"use client";

import { useState } from "react";
import { Search, Phone, MapPin } from "lucide-react";

interface AvailableNumber {
  phone_number: string;
  friendly_name: string;
  locality: string | null;
  region: string | null;
  iso_country: string;
}

interface BuyBotelierFormProps {
  onNumberAdded: () => void;
  onClose: () => void;
}

export default function BuyBotelierForm({ onNumberAdded, onClose }: BuyBotelierFormProps) {
  const [areaCode, setAreaCode] = useState("");
  const [country, setCountry] = useState("US");
  const [searching, setSearching] = useState(false);
  const [availableNumbers, setAvailableNumbers] = useState<AvailableNumber[]>([]);
  const [selectedNumber, setSelectedNumber] = useState<string | null>(null);
  const [friendlyName, setFriendlyName] = useState("");
  const [purchasing, setPurchasing] = useState(false);

  const handleSearch = async () => {
    setSearching(true);
    try {
      const hotelId = "6b410bcc-f843-40df-b32d-078d3e01ac7f"; // Demo Hotel ID
      const params = new URLSearchParams({
        hotel_id: hotelId,
        country,
        limit: "10",
      });
      
      if (areaCode) {
        params.append("area_code", areaCode);
      }

      const response = await fetch(`http://localhost:8000/api/phone-numbers/available?${params}`);
      const data = await response.json();
      setAvailableNumbers(data);
    } catch (error) {
      console.error("Failed to search numbers:", error);
      alert("Failed to search for available numbers");
    } finally {
      setSearching(false);
    }
  };

  const handlePurchase = async () => {
    if (!selectedNumber) return;

    setPurchasing(true);
    try {
      const hotelId = "6b410bcc-f843-40df-b32d-078d3e01ac7f"; // Demo Hotel ID
      const response = await fetch("http://localhost:8000/api/phone-numbers/purchase", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          phone_number: selectedNumber,
          friendly_name: friendlyName || null,
          hotel_id: hotelId,
        }),
      });

      if (response.ok) {
        onNumberAdded();
      } else {
        const error = await response.json();
        alert(`Failed to purchase number: ${error.detail}`);
      }
    } catch (error) {
      console.error("Failed to purchase number:", error);
      alert("Failed to purchase number");
    } finally {
      setPurchasing(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold text-white mb-4">Search Available Numbers</h3>
        
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">
              Area Code
            </label>
            <input
              type="text"
              value={areaCode}
              onChange={(e) => setAreaCode(e.target.value.replace(/\D/g, "").slice(0, 3))}
              placeholder="e.g. 415, 212, 310"
              className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-4 py-2 text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
              maxLength={3}
            />
            <p className="text-xs text-gray-500 mt-1">Leave empty to search all area codes</p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">
              Country
            </label>
            <select
              value={country}
              onChange={(e) => setCountry(e.target.value)}
              className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:border-blue-500"
            >
              <option value="US">United States</option>
              <option value="GB">United Kingdom</option>
              <option value="CA">Canada</option>
            </select>
          </div>

          <button
            onClick={handleSearch}
            disabled={searching}
            className="w-full flex items-center justify-center space-x-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-700 text-white px-4 py-2 rounded-lg transition-colors"
          >
            <Search className="h-5 w-5" />
            <span>{searching ? "Searching..." : "Search Numbers"}</span>
          </button>
        </div>
      </div>

      {availableNumbers.length > 0 && (
        <div>
          <h3 className="text-lg font-semibold text-white mb-4">Available Numbers</h3>
          <div className="space-y-2 max-h-96 overflow-y-auto">
            {availableNumbers.map((number) => (
              <button
                key={number.phone_number}
                onClick={() => setSelectedNumber(number.phone_number)}
                className={`w-full text-left p-4 rounded-lg border transition-colors ${
                  selectedNumber === number.phone_number
                    ? "bg-blue-600/10 border-blue-500"
                    : "bg-[#1a1a1a] border-gray-700 hover:border-gray-600"
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-3">
                    <Phone className="h-5 w-5 text-blue-500" />
                    <div>
                      <div className="text-white font-medium">{number.friendly_name}</div>
                      {number.locality && number.region && (
                        <div className="flex items-center space-x-1 text-sm text-gray-400 mt-1">
                          <MapPin className="h-3 w-3" />
                          <span>{number.locality}, {number.region}</span>
                        </div>
                      )}
                    </div>
                  </div>
                  {selectedNumber === number.phone_number && (
                    <div className="w-5 h-5 bg-blue-600 rounded-full flex items-center justify-center">
                      <div className="w-2 h-2 bg-white rounded-full"></div>
                    </div>
                  )}
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {selectedNumber && (
        <div>
          <h3 className="text-lg font-semibold text-white mb-4">Configure Number</h3>
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-2">
                Label (Optional)
              </label>
              <input
                type="text"
                value={friendlyName}
                onChange={(e) => setFriendlyName(e.target.value)}
                placeholder="e.g. Front Desk, Reservations"
                className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-4 py-2 text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
              />
            </div>

            <div className="flex space-x-3">
              <button
                onClick={onClose}
                className="flex-1 px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handlePurchase}
                disabled={purchasing}
                className="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-700 text-white rounded-lg transition-colors"
              >
                {purchasing ? "Purchasing..." : "Purchase Number"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
