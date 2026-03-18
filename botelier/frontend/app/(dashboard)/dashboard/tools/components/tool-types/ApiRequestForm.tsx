"use client";

import { useState, useEffect } from "react";
import { Globe, Plus, Trash2, ChevronDown, ChevronRight } from "lucide-react";
import { notify } from "@/lib/notifications";
import { useAuthToken } from "@/lib/auth/useAuthToken";

interface Tool {
  id: string;
  name: string;
  description: string;
  tool_type: string;
  config: any;
  is_active: boolean;
}

interface ApiRequestFormProps {
  onSuccess: (tool: any) => void;
  onCancel: () => void;
  tool?: Tool;
  accountId: string;
  toolSetId?: string;
}

interface Parameter {
  name: string;
  type: string;
  description: string;
  required: boolean;
}

interface HeaderEntry {
  key: string;
  value: string;
}

interface ResponseMappingEntry {
  variable: string;
  jsonPath: string;
}

export default function ApiRequestForm({ onSuccess, onCancel, tool, accountId, toolSetId }: ApiRequestFormProps) {
  const isEditMode = !!tool;
  const { authFetch } = useAuthToken();

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [method, setMethod] = useState<string>("GET");
  const [url, setUrl] = useState("");
  const [headers, setHeaders] = useState<HeaderEntry[]>([]);
  const [parameters, setParameters] = useState<Parameter[]>([]);
  const [bodyTemplate, setBodyTemplate] = useState("");
  const [responseMappings, setResponseMappings] = useState<ResponseMappingEntry[]>([]);
  const [responseInstructions, setResponseInstructions] = useState("");
  const [timeout, setTimeout_] = useState(30);

  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [showHeaders, setShowHeaders] = useState(false);
  const [showResponseMapping, setShowResponseMapping] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);

  useEffect(() => {
    if (tool) {
      setName(tool.name || "");
      setDescription(tool.description || "");
      setMethod(tool.config?.method || "GET");
      setUrl(tool.config?.url || "");
      setTimeout_(tool.config?.timeout || 30);
      setResponseInstructions(tool.config?.response_instructions || "");
      setBodyTemplate(tool.config?.body_template || "");

      if (tool.config?.headers && Object.keys(tool.config.headers).length > 0) {
        setHeaders(
          Object.entries(tool.config.headers).map(([key, value]) => ({ key, value: value as string }))
        );
        setShowHeaders(true);
      }

      if (tool.config?.parameters && Object.keys(tool.config.parameters).length > 0) {
        setParameters(
          Object.entries(tool.config.parameters).map(([paramName, paramConfig]: [string, any]) => ({
            name: paramName,
            type: paramConfig.type || "string",
            description: paramConfig.description || "",
            required: paramConfig.required || false,
          }))
        );
      }

      if (tool.config?.response_mapping && Object.keys(tool.config.response_mapping).length > 0) {
        setResponseMappings(
          Object.entries(tool.config.response_mapping).map(([variable, jsonPath]) => ({
            variable,
            jsonPath: jsonPath as string,
          }))
        );
        setShowResponseMapping(true);
      }
    }
  }, [tool]);

  const validate = (): boolean => {
    const newErrors: Record<string, string> = {};
    if (!name.trim()) newErrors.name = "Tool name is required";
    if (!description.trim()) newErrors.description = "Description is required";
    if (!url.trim()) newErrors.url = "URL is required";
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validate()) return;

    setSaving(true);
    try {
      const headersObj: Record<string, string> = {};
      headers.forEach((h) => {
        if (h.key.trim()) headersObj[h.key.trim()] = h.value;
      });

      const paramsObj: Record<string, any> = {};
      parameters.forEach((p) => {
        if (p.name.trim()) {
          paramsObj[p.name.trim()] = {
            type: p.type,
            description: p.description,
            required: p.required,
          };
        }
      });

      const responseMappingObj: Record<string, string> = {};
      responseMappings.forEach((rm) => {
        if (rm.variable.trim() && rm.jsonPath.trim()) {
          responseMappingObj[rm.variable.trim()] = rm.jsonPath.trim();
        }
      });

      const payload = {
        name,
        description,
        tool_type: "API_REQUEST",
        config: {
          url,
          method,
          headers: Object.keys(headersObj).length > 0 ? headersObj : undefined,
          parameters: Object.keys(paramsObj).length > 0 ? paramsObj : undefined,
          body_template: bodyTemplate.trim() || undefined,
          response_mapping: Object.keys(responseMappingObj).length > 0 ? responseMappingObj : undefined,
          response_instructions: responseInstructions.trim() || undefined,
          timeout,
        },
        tool_set_id: toolSetId,
        is_active: true,
      };

      const scopeParam = toolSetId ? `tool_set_id=${toolSetId}` : `hotel_id=${accountId}`;
      const apiUrl = isEditMode
        ? `/api/tools/${tool.id}?${scopeParam}`
        : "/api/tools";
      const apiMethod = isEditMode ? "PUT" : "POST";

      const response = await authFetch(apiUrl, {
        method: apiMethod,
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        const errorData = await response.json();
        let errorMsg = `Failed to ${isEditMode ? "update" : "create"} tool`;
        if (typeof errorData.detail === "string") {
          errorMsg = errorData.detail;
        } else if (Array.isArray(errorData.detail)) {
          errorMsg = errorData.detail.map((e: any) => e.msg || e.message || JSON.stringify(e)).join(", ");
        }
        throw new Error(errorMsg);
      }

      const savedTool = await response.json();
      notify.success(`Tool ${isEditMode ? "updated" : "created"} successfully`);
      onSuccess(savedTool);
    } catch (error) {
      console.error(`Error ${isEditMode ? "updating" : "creating"} tool:`, error);
      notify.error(error instanceof Error ? error.message : "Failed to save tool");
    } finally {
      setSaving(false);
    }
  };

  const addHeader = () => setHeaders([...headers, { key: "", value: "" }]);
  const removeHeader = (i: number) => setHeaders(headers.filter((_, idx) => idx !== i));
  const updateHeader = (i: number, field: "key" | "value", val: string) => {
    const updated = [...headers];
    updated[i][field] = val;
    setHeaders(updated);
  };

  const addParameter = () => setParameters([...parameters, { name: "", type: "string", description: "", required: false }]);
  const removeParameter = (i: number) => setParameters(parameters.filter((_, idx) => idx !== i));
  const updateParameter = (i: number, field: keyof Parameter, val: any) => {
    const updated = [...parameters];
    (updated[i] as any)[field] = val;
    setParameters(updated);
  };

  const addResponseMapping = () => setResponseMappings([...responseMappings, { variable: "", jsonPath: "" }]);
  const removeResponseMapping = (i: number) => setResponseMappings(responseMappings.filter((_, idx) => idx !== i));
  const updateResponseMapping = (i: number, field: "variable" | "jsonPath", val: string) => {
    const updated = [...responseMappings];
    updated[i][field] = val;
    setResponseMappings(updated);
  };

  const inputClass = (hasError?: boolean) =>
    `w-full px-4 py-3 bg-[#141414] border ${hasError ? "border-red-500" : "border-gray-800"} rounded-lg focus:outline-none focus:ring-2 focus:ring-purple-600 focus:border-transparent`;
  const smallInputClass =
    "w-full px-3 py-2 bg-[#141414] border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-purple-600 focus:border-transparent font-mono";

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <div className="flex items-center gap-3 pb-4 border-b border-gray-800">
        <div className="w-12 h-12 rounded-lg bg-purple-600/20 flex items-center justify-center">
          <Globe className="text-purple-500" size={24} />
        </div>
        <div>
          <h3 className="font-semibold">{isEditMode ? "Edit" : "Create"} API Request Tool</h3>
          <p className="text-sm text-gray-400">Call external APIs during voice conversations</p>
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium mb-2">
          Tool Name <span className="text-red-500">*</span>
        </label>
        <input
          type="text"
          value={name}
          onChange={(e) => { setName(e.target.value); setErrors({ ...errors, name: "" }); }}
          placeholder="e.g., check_reservation"
          className={inputClass(!!errors.name)}
        />
        <p className="text-xs text-gray-500 mt-1">Used internally by the AI (lowercase, underscores)</p>
        {errors.name && <p className="text-xs text-red-500 mt-1">{errors.name}</p>}
      </div>

      <div>
        <label className="block text-sm font-medium mb-2">
          Description <span className="text-red-500">*</span>
        </label>
        <textarea
          value={description}
          onChange={(e) => { setDescription(e.target.value); setErrors({ ...errors, description: "" }); }}
          placeholder="Describe when the AI should call this API (e.g., 'Look up a guest reservation by confirmation number')"
          rows={3}
          className={`${inputClass(!!errors.description)} resize-none`}
        />
        <p className="text-xs text-gray-500 mt-1">The AI uses this to decide when to call this function</p>
        {errors.description && <p className="text-xs text-red-500 mt-1">{errors.description}</p>}
      </div>

      <div className="grid grid-cols-4 gap-3">
        <div>
          <label className="block text-sm font-medium mb-2">Method</label>
          <select
            value={method}
            onChange={(e) => setMethod(e.target.value)}
            className="w-full px-4 py-3 bg-[#141414] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-purple-600 focus:border-transparent"
          >
            <option value="GET">GET</option>
            <option value="POST">POST</option>
            <option value="PUT">PUT</option>
            <option value="DELETE">DELETE</option>
            <option value="PATCH">PATCH</option>
          </select>
        </div>
        <div className="col-span-3">
          <label className="block text-sm font-medium mb-2">
            URL <span className="text-red-500">*</span>
          </label>
          <input
            type="text"
            value={url}
            onChange={(e) => { setUrl(e.target.value); setErrors({ ...errors, url: "" }); }}
            placeholder="https://api.example.com/reservations/{confirmation_number}"
            className={`${inputClass(!!errors.url)} font-mono text-sm`}
          />
          <p className="text-xs text-gray-500 mt-1">
            Use {"{parameter_name}"} for dynamic values from parameters
          </p>
          {errors.url && <p className="text-xs text-red-500 mt-1">{errors.url}</p>}
        </div>
      </div>

      <div className="space-y-4">
        <h4 className="text-sm font-semibold text-gray-300 border-b border-gray-800 pb-2">Parameters</h4>
        <p className="text-xs text-gray-500">
          Define the data the AI needs to collect from the caller to make the request. These become function arguments.
        </p>
        {parameters.map((param, i) => (
          <div key={i} className="grid grid-cols-12 gap-2 items-start">
            <div className="col-span-3">
              <input
                type="text"
                value={param.name}
                onChange={(e) => updateParameter(i, "name", e.target.value)}
                placeholder="param_name"
                className={smallInputClass}
              />
            </div>
            <div className="col-span-2">
              <select
                value={param.type}
                onChange={(e) => updateParameter(i, "type", e.target.value)}
                className="w-full px-3 py-2 bg-[#141414] border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-purple-600 focus:border-transparent"
              >
                <option value="string">String</option>
                <option value="number">Number</option>
                <option value="integer">Integer</option>
                <option value="boolean">Boolean</option>
              </select>
            </div>
            <div className="col-span-4">
              <input
                type="text"
                value={param.description}
                onChange={(e) => updateParameter(i, "description", e.target.value)}
                placeholder="Description for AI"
                className={smallInputClass}
              />
            </div>
            <div className="col-span-2 flex items-center gap-2 pt-1">
              <label className="flex items-center gap-1 text-xs text-gray-400 cursor-pointer">
                <input
                  type="checkbox"
                  checked={param.required}
                  onChange={(e) => updateParameter(i, "required", e.target.checked)}
                  className="rounded bg-[#141414] border-gray-700 text-purple-600 focus:ring-purple-600"
                />
                Required
              </label>
            </div>
            <div className="col-span-1 flex justify-end">
              <button
                type="button"
                onClick={() => removeParameter(i)}
                className="p-1.5 text-red-400 hover:text-red-300 hover:bg-red-900/20 rounded transition-colors"
              >
                <Trash2 size={14} />
              </button>
            </div>
          </div>
        ))}
        <button
          type="button"
          onClick={addParameter}
          className="flex items-center gap-2 text-sm text-purple-400 hover:text-purple-300 transition-colors"
        >
          <Plus size={14} /> Add Parameter
        </button>
      </div>

      <div>
        <button
          type="button"
          onClick={() => setShowHeaders(!showHeaders)}
          className="flex items-center gap-2 text-sm font-semibold text-gray-300 mb-2"
        >
          {showHeaders ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          Headers
          {headers.length > 0 && <span className="text-xs text-gray-500">({headers.length})</span>}
        </button>

        {showHeaders && (
          <div className="space-y-2 pl-4">
            {headers.map((header, i) => (
              <div key={i} className="flex gap-2 items-center">
                <input
                  type="text"
                  value={header.key}
                  onChange={(e) => updateHeader(i, "key", e.target.value)}
                  placeholder="Header-Name"
                  className={`flex-1 ${smallInputClass}`}
                />
                <input
                  type="text"
                  value={header.value}
                  onChange={(e) => updateHeader(i, "value", e.target.value)}
                  placeholder="value"
                  className={`flex-1 ${smallInputClass}`}
                />
                <button
                  type="button"
                  onClick={() => removeHeader(i)}
                  className="p-1.5 text-red-400 hover:text-red-300 hover:bg-red-900/20 rounded transition-colors"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
            <button
              type="button"
              onClick={addHeader}
              className="flex items-center gap-2 text-sm text-purple-400 hover:text-purple-300 transition-colors"
            >
              <Plus size={14} /> Add Header
            </button>
          </div>
        )}
      </div>

      {(method === "POST" || method === "PUT" || method === "PATCH") && (
        <div>
          <label className="block text-sm font-medium mb-2">
            Request Body (JSON)
            <span className="text-xs text-purple-400 ml-2">Use {"{parameter_name}"} for dynamic values</span>
          </label>
          <textarea
            value={bodyTemplate}
            onChange={(e) => setBodyTemplate(e.target.value)}
            rows={5}
            className={`${inputClass()} resize-none font-mono text-sm`}
            placeholder={'{\n  "confirmation_number": "{confirmation_number}",\n  "guest_name": "{guest_name}"\n}'}
          />
        </div>
      )}

      <div>
        <button
          type="button"
          onClick={() => setShowResponseMapping(!showResponseMapping)}
          className="flex items-center gap-2 text-sm font-semibold text-gray-300 mb-2"
        >
          {showResponseMapping ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          Response Mapping
          {responseMappings.length > 0 && <span className="text-xs text-gray-500">({responseMappings.length})</span>}
        </button>

        {showResponseMapping && (
          <div className="space-y-2 pl-4">
            <p className="text-xs text-gray-500 mb-2">
              Extract specific fields from the API response. Use dot notation for nested values (e.g., data.guest.name).
            </p>
            {responseMappings.map((rm, i) => (
              <div key={i} className="flex gap-2 items-center">
                <input
                  type="text"
                  value={rm.variable}
                  onChange={(e) => updateResponseMapping(i, "variable", e.target.value)}
                  placeholder="variable_name"
                  className={`flex-1 ${smallInputClass}`}
                />
                <span className="text-gray-500 text-sm">=</span>
                <input
                  type="text"
                  value={rm.jsonPath}
                  onChange={(e) => updateResponseMapping(i, "jsonPath", e.target.value)}
                  placeholder="response.data.field"
                  className={`flex-1 ${smallInputClass}`}
                />
                <button
                  type="button"
                  onClick={() => removeResponseMapping(i)}
                  className="p-1.5 text-red-400 hover:text-red-300 hover:bg-red-900/20 rounded transition-colors"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
            <button
              type="button"
              onClick={addResponseMapping}
              className="flex items-center gap-2 text-sm text-purple-400 hover:text-purple-300 transition-colors"
            >
              <Plus size={14} /> Add Mapping
            </button>
          </div>
        )}
      </div>

      <div>
        <label className="block text-sm font-medium mb-2">
          Response Instructions for AI
        </label>
        <textarea
          value={responseInstructions}
          onChange={(e) => setResponseInstructions(e.target.value)}
          rows={3}
          className={`${inputClass()} resize-none`}
          placeholder="e.g., Summarize the reservation details to the guest: their room type, check-in/out dates, and total cost. If the reservation is not found, apologize and offer to help them check again."
        />
        <p className="text-xs text-gray-500 mt-1">
          Tell the AI how to interpret and present the API response to the caller
        </p>
      </div>

      <div>
        <button
          type="button"
          onClick={() => setShowAdvanced(!showAdvanced)}
          className="flex items-center gap-2 text-sm font-semibold text-gray-300 mb-2"
        >
          {showAdvanced ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          Advanced Settings
        </button>

        {showAdvanced && (
          <div className="space-y-4 pl-4">
            <div>
              <label className="block text-sm font-medium mb-2">Timeout (seconds)</label>
              <input
                type="number"
                value={timeout}
                onChange={(e) => setTimeout_(parseInt(e.target.value) || 30)}
                min={1}
                max={120}
                className="w-32 px-4 py-3 bg-[#141414] border border-gray-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-purple-600 focus:border-transparent"
              />
            </div>
          </div>
        )}
      </div>

      <div className="flex gap-3 pt-4">
        <button
          type="button"
          onClick={onCancel}
          className="flex-1 px-6 py-3 bg-gray-800 hover:bg-gray-700 rounded-lg font-medium transition-colors"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={saving}
          className="flex-1 px-6 py-3 bg-purple-600 hover:bg-purple-700 rounded-lg font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {saving ? (isEditMode ? "Saving..." : "Creating...") : isEditMode ? "Save Changes" : "Create Tool"}
        </button>
      </div>
    </form>
  );
}
