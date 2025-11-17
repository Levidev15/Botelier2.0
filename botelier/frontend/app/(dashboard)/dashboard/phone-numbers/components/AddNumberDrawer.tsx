"use client";

import { useState } from "react";
import { X, Phone, Upload, Network } from "lucide-react";
import BuyBotelierForm from "./number-types/BuyBotelierForm";

interface AddNumberDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  onNumberAdded: () => void;
}

type NumberOption = "buy" | "import_twilio" | "byot";

export default function AddNumberDrawer({ isOpen, onClose, onNumberAdded }: AddNumberDrawerProps) {
  const [selectedOption, setSelectedOption] = useState<NumberOption>("buy");

  if (!isOpen) return null;

  return (
    <>
      <div
        className="fixed inset-0 bg-black/50 z-40"
        onClick={onClose}
      ></div>

      <div className="fixed right-0 top-0 bottom-0 w-full max-w-2xl bg-[#0a0a0a] border-l border-gray-800 z-50 overflow-auto">
        <div className="sticky top-0 bg-[#0a0a0a] border-b border-gray-800 px-6 py-4 flex items-center justify-between">
          <h2 className="text-xl font-semibold text-white">Phone Number Options</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white transition-colors"
          >
            <X className="h-6 w-6" />
          </button>
        </div>

        <div className="flex h-[calc(100%-73px)]">
          <div className="w-64 bg-[#141414] border-r border-gray-800 p-4">
            <div className="space-y-1">
              <button
                onClick={() => setSelectedOption("buy")}
                className={`w-full flex items-center space-x-3 px-4 py-3 rounded-lg transition-colors text-left ${
                  selectedOption === "buy"
                    ? "bg-blue-600/10 text-blue-400"
                    : "text-gray-400 hover:bg-gray-800 hover:text-gray-200"
                }`}
              >
                <Phone className="h-5 w-5" />
                <span className="text-sm font-medium">Buy Botelier Number</span>
              </button>

              <button
                onClick={() => setSelectedOption("import_twilio")}
                className={`w-full flex items-center space-x-3 px-4 py-3 rounded-lg transition-colors text-left ${
                  selectedOption === "import_twilio"
                    ? "bg-blue-600/10 text-blue-400"
                    : "text-gray-400 hover:bg-gray-800 hover:text-gray-200"
                }`}
              >
                <Upload className="h-5 w-5" />
                <span className="text-sm font-medium">Import Twilio</span>
              </button>

              <button
                onClick={() => setSelectedOption("byot")}
                className={`w-full flex items-center space-x-3 px-4 py-3 rounded-lg transition-colors text-left ${
                  selectedOption === "byot"
                    ? "bg-blue-600/10 text-blue-400"
                    : "text-gray-400 hover:bg-gray-800 hover:text-gray-200"
                }`}
              >
                <Network className="h-5 w-5" />
                <span className="text-sm font-medium">BYOT SIP Trunk Number</span>
              </button>
            </div>
          </div>

          <div className="flex-1 p-6">
            {selectedOption === "buy" && (
              <BuyBotelierForm onNumberAdded={onNumberAdded} onClose={onClose} />
            )}

            {selectedOption === "import_twilio" && (
              <div className="text-center py-12">
                <Upload className="h-12 w-12 text-gray-600 mx-auto mb-4" />
                <h3 className="text-lg font-semibold text-white mb-2">Import from Twilio</h3>
                <p className="text-gray-400">Coming soon</p>
              </div>
            )}

            {selectedOption === "byot" && (
              <div className="text-center py-12">
                <Network className="h-12 w-12 text-gray-600 mx-auto mb-4" />
                <h3 className="text-lg font-semibold text-white mb-2">BYOT SIP Trunk</h3>
                <p className="text-gray-400">Coming soon</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
