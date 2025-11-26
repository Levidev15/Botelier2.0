"use client";

export interface SlotTrackerProps {
  collectedSlots: Record<string, unknown>;
  variablesToCollect: Array<{
    key: string;
    type: string;
    description: string;
    required: boolean;
    choices?: string[];
  }>;
  progress: {
    total_slots?: number;
    required_slots?: number;
    collected_slots?: number;
    required_collected?: number;
    is_complete?: boolean;
    collected?: number;
    total?: number;
    percentage?: number;
  };
  compact?: boolean;
}

export default function SlotTracker({
  collectedSlots,
  variablesToCollect,
  progress,
  compact,
}: SlotTrackerProps) {
  const collected = progress.collected_slots ?? progress.collected ?? 0;
  const total = progress.total_slots ?? progress.total ?? variablesToCollect.length;
  const percentage = total > 0 ? Math.round((collected / total) * 100) : 0;

  if (compact) {
    return (
      <div className="space-y-1.5">
        <div className="w-full bg-[#2a2a2a] rounded-full h-1.5">
          <div
            className="bg-blue-500 h-1.5 rounded-full transition-all duration-300"
            style={{ width: `${percentage}%` }}
          />
        </div>
        <div className="space-y-1">
          {variablesToCollect.map((variable) => {
            const isCollected = variable.key in collectedSlots;
            const value = collectedSlots[variable.key];

            return (
              <div
                key={variable.key}
                className={`flex items-center justify-between py-1 px-2 rounded text-xs ${
                  isCollected ? "bg-green-900/20" : "bg-[#2a2a2a]"
                }`}
              >
                <div className="flex items-center gap-1.5">
                  <span
                    className={`w-1.5 h-1.5 rounded-full ${
                      isCollected ? "bg-green-500" : "bg-gray-500"
                    }`}
                  />
                  <span className="text-gray-300 font-mono">{variable.key}</span>
                </div>
                {isCollected && (
                  <span className="text-green-400 font-mono truncate max-w-[100px]">
                    {String(value)}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  return (
    <div className="bg-[#1a1a1a] rounded-lg border border-[#2a2a2a] p-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-medium text-gray-300">Collected Data</h3>
        <span className="text-xs text-gray-500">
          {collected}/{total} ({percentage}%)
        </span>
      </div>

      <div className="mb-3">
        <div className="w-full bg-[#2a2a2a] rounded-full h-2">
          <div
            className="bg-blue-500 h-2 rounded-full transition-all duration-300"
            style={{ width: `${percentage}%` }}
          />
        </div>
      </div>

      <div className="space-y-2">
        {variablesToCollect.map((variable) => {
          const isCollected = variable.key in collectedSlots;
          const value = collectedSlots[variable.key];

          return (
            <div
              key={variable.key}
              className={`flex items-start justify-between p-2 rounded ${
                isCollected ? "bg-green-900/20" : "bg-[#2a2a2a]"
              }`}
            >
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span
                    className={`w-2 h-2 rounded-full ${
                      isCollected ? "bg-green-500" : "bg-gray-500"
                    }`}
                  />
                  <span className="text-sm font-medium text-gray-200">
                    {variable.key}
                  </span>
                  <span className="text-xs text-gray-500 bg-[#3a3a3a] px-1.5 py-0.5 rounded">
                    {variable.type}
                  </span>
                  {variable.required && (
                    <span className="text-xs text-red-400">*</span>
                  )}
                </div>
                <p className="text-xs text-gray-500 ml-4 mt-0.5">
                  {variable.description}
                </p>
              </div>

              {isCollected && (
                <div className="ml-2 text-right">
                  <span className="text-sm text-green-400 font-mono">
                    {String(value)}
                  </span>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
