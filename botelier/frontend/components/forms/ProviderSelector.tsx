"use client";

interface ProviderOption {
  value: string;
  label: string;
}

interface ProviderSelectorProps {
  label: string;
  description?: string;
  providerValue: string;
  modelValue: string;
  providers: ProviderOption[];
  models: ProviderOption[];
  onProviderChange: (value: string) => void;
  onModelChange: (value: string) => void;
  disabled?: boolean;
}

export default function ProviderSelector({
  label,
  description,
  providerValue,
  modelValue,
  providers,
  models,
  onProviderChange,
  onModelChange,
  disabled = false,
}: ProviderSelectorProps) {
  return (
    <div className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-gray-200 mb-2">
          {label} Provider
        </label>
        {description && (
          <p className="text-xs text-gray-500 mb-2">{description}</p>
        )}
        <select
          value={providerValue}
          onChange={(e) => onProviderChange(e.target.value)}
          disabled={disabled}
          className="w-full px-3 py-2 bg-[#141414] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <option value="">Select provider...</option>
          {providers.map((provider) => (
            <option key={provider.value} value={provider.value}>
              {provider.label}
            </option>
          ))}
        </select>
      </div>

      {providerValue && models.length > 0 && (
        <div>
          <label className="block text-sm font-medium text-gray-200 mb-2">
            {label} Model/Voice
          </label>
          <select
            value={modelValue}
            onChange={(e) => onModelChange(e.target.value)}
            disabled={disabled}
            className="w-full px-3 py-2 bg-[#141414] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-600 text-sm disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <option value="">Select model/voice...</option>
            {models.map((model) => (
              <option key={model.value} value={model.value}>
                {model.label}
              </option>
            ))}
          </select>
        </div>
      )}
    </div>
  );
}
