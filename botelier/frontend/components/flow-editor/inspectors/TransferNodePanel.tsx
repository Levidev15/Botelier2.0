"use client";

import { useFlowStore, TransferNodeData } from "../store";

interface Props {
  data: TransferNodeData;
  nodeId: string;
}

export default function TransferNodePanel({ data, nodeId }: Props) {
  const { updateNodeData } = useFlowStore();
  const transfer = data.transfer || { phoneNumber: "", preTransferMessage: "", transferMode: "warm" as const };

  const updateTransfer = (updates: Partial<typeof transfer>) => {
    updateNodeData(nodeId, { transfer: { ...transfer, ...updates } });
  };

  const transferMode = transfer.transferMode || "warm";

  return (
    <div className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-gray-400 mb-1">Transfer To (Phone Number)</label>
        <input
          type="text"
          value={transfer.phoneNumber || ""}
          onChange={(e) => updateTransfer({ phoneNumber: e.target.value })}
          className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-cyan-500 focus:outline-none"
          placeholder="+1234567890"
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-400 mb-1">Pre-Transfer Message</label>
        <textarea
          value={transfer.preTransferMessage || ""}
          onChange={(e) => updateTransfer({ preTransferMessage: e.target.value })}
          rows={2}
          className="w-full bg-[#1a1a1a] border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-cyan-500 focus:outline-none resize-none"
          placeholder="Let me connect you with our front desk team. Please hold."
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-400 mb-2">Transfer Mode</label>
        <div className="space-y-2">
          <button
            type="button"
            onClick={() => updateTransfer({ transferMode: "warm" })}
            className={`w-full text-left px-3 py-2.5 rounded-lg border transition-colors ${
              transferMode === "warm"
                ? "border-cyan-600 bg-cyan-900/20"
                : "border-gray-700 bg-[#1a1a1a] hover:border-gray-600"
            }`}
          >
            <div className="flex items-start gap-2">
              <div className={`mt-0.5 w-3.5 h-3.5 rounded-full border-2 flex items-center justify-center flex-shrink-0 ${
                transferMode === "warm" ? "border-cyan-500" : "border-gray-600"
              }`}>
                {transferMode === "warm" && <div className="w-1.5 h-1.5 rounded-full bg-cyan-500" />}
              </div>
              <div>
                <div className="text-xs font-medium text-white">Warm Transfer</div>
                <div className="text-xs text-gray-500 mt-0.5">Twilio bridges both legs. Full logging and duration tracking. Standard charges apply.</div>
              </div>
            </div>
          </button>

          <button
            type="button"
            onClick={() => updateTransfer({ transferMode: "cold" })}
            className={`w-full text-left px-3 py-2.5 rounded-lg border transition-colors ${
              transferMode === "cold"
                ? "border-amber-600 bg-amber-900/20"
                : "border-gray-700 bg-[#1a1a1a] hover:border-gray-600"
            }`}
          >
            <div className="flex items-start gap-2">
              <div className={`mt-0.5 w-3.5 h-3.5 rounded-full border-2 flex items-center justify-center flex-shrink-0 ${
                transferMode === "cold" ? "border-amber-500" : "border-gray-600"
              }`}>
                {transferMode === "cold" && <div className="w-1.5 h-1.5 rounded-full bg-amber-500" />}
              </div>
              <div>
                <div className="text-xs font-medium text-white">Cold Transfer (SIP REFER)</div>
                <div className="text-xs text-gray-500 mt-0.5">Twilio exits after handoff. No ongoing charges. Call outcome not tracked.</div>
              </div>
            </div>
          </button>
        </div>

        {transferMode === "cold" && (
          <div className="mt-2 flex items-start gap-1.5 px-2.5 py-2 bg-amber-950/30 border border-amber-800/40 rounded-lg">
            <span className="text-amber-500 text-xs flex-shrink-0 mt-0.5">⚠</span>
            <p className="text-xs text-amber-400">
              After transfer, Botelier can no longer monitor or log this call.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
