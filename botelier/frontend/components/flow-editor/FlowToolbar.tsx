"use client";

import { useState } from "react";
import { 
  Save, 
  Undo2, 
  Redo2, 
  Plus, 
  Layout, 
  ChevronDown,
  Play,
  MessageSquare,
  FormInput,
  ClipboardList,
  Globe,
  GitBranch,
  Route,
  CheckCircle2,
  Variable,
  PhoneForwarded,
  PhoneOff,
  FlaskConical,
  Upload,
  History,
  FileEdit,
  RotateCcw,
  Trash2,
  Info,
  X,
  Settings
} from "lucide-react";
import { useFlowStore, NodeType, AVAILABLE_TEMPLATES, FlowVersionInfo } from "./store";
import { toast } from "sonner";

interface FlowToolbarProps {
  onSave: () => void;
  isSaving: boolean;
  showSimulator?: boolean;
  onToggleSimulator?: () => void;
}

interface NodeInfo {
  type: NodeType;
  label: string;
  icon: React.ReactNode;
  color: string;
  description: string;
  whenToUse: string;
  example: string;
}

const nodeTypeConfig: NodeInfo[] = [
  { 
    type: "initial", 
    label: "Start", 
    icon: <Play className="h-3 w-3" />, 
    color: "bg-green-500",
    description: "The entry point of your conversation flow. Every flow needs exactly one Start node.",
    whenToUse: "Always required as the first node. Sets the greeting message and system instructions for the AI.",
    example: "\"Thank you for calling Grand Hotel. How may I assist you today?\""
  },
  { 
    type: "message", 
    label: "Message", 
    icon: <MessageSquare className="h-3 w-3" />, 
    color: "bg-blue-500",
    description: "Speaks a message to the guest without waiting for a response. Can include collected variables.",
    whenToUse: "Use to provide information, confirmations, or transition messages between steps.",
    example: "\"I'll now check availability for your requested dates.\""
  },
  { 
    type: "collect_slot", 
    label: "Collect Input", 
    icon: <FormInput className="h-3 w-3" />, 
    color: "bg-purple-500",
    description: "Asks the guest for a single piece of information and stores it in a variable.",
    whenToUse: "Use for collecting one data point like a name, date, or number. For multiple fields, consider Collect Form.",
    example: "Collecting guest name: \"May I have your name please?\""
  },
  { 
    type: "collect_form", 
    label: "Collect Form", 
    icon: <ClipboardList className="h-3 w-3" />, 
    color: "bg-violet-500",
    description: "Collects multiple pieces of information in sequence. Consolidates several inputs into one node.",
    whenToUse: "Use for booking forms, registration, or any multi-field data collection. Keeps your flow clean.",
    example: "Collecting check-in date, check-out date, and number of guests in one node."
  },
  { 
    type: "confirmation", 
    label: "Confirmation", 
    icon: <CheckCircle2 className="h-3 w-3" />, 
    color: "bg-emerald-500",
    description: "Summarizes collected information and asks the guest to confirm before proceeding.",
    whenToUse: "Use before submitting bookings or making changes to verify details are correct.",
    example: "\"You're booking a Deluxe Room for Dec 15-18 for 2 guests. Is this correct?\""
  },
  { 
    type: "api_request", 
    label: "API Request", 
    icon: <Globe className="h-3 w-3" />, 
    color: "bg-orange-500",
    description: "Calls an external API to check availability, submit bookings, or fetch data.",
    whenToUse: "Use to integrate with your booking system, CRM, or other hotel services.",
    example: "Calling your reservation system to check room availability for the selected dates."
  },
  { 
    type: "condition", 
    label: "Condition", 
    icon: <GitBranch className="h-3 w-3" />, 
    color: "bg-yellow-500",
    description: "Branches the flow based on a condition. Routes to different paths based on variable values.",
    whenToUse: "Use to handle different scenarios like available vs. sold out, member vs. non-member.",
    example: "If rooms are available, continue to booking. If not, offer alternative dates."
  },
  { 
    type: "router", 
    label: "Router", 
    icon: <Route className="h-3 w-3" />, 
    color: "bg-indigo-500",
    description: "Lets the AI decide which path to take based on what the guest wants.",
    whenToUse: "Use for main menus or when the guest could have multiple intents.",
    example: "Routes to booking, room service, concierge, or general inquiries based on guest request."
  },
  { 
    type: "set_variable", 
    label: "Set Variable", 
    icon: <Variable className="h-3 w-3" />, 
    color: "bg-teal-500",
    description: "Creates or modifies a variable without asking the guest. Can combine, format, or calculate values.",
    whenToUse: "Use to prepare data for APIs, combine fields, or set default values.",
    example: "Combining first and last name into full_name, or calculating total nights from dates."
  },
  { 
    type: "transfer", 
    label: "Transfer Call", 
    icon: <PhoneForwarded className="h-3 w-3" />, 
    color: "bg-cyan-500",
    description: "Transfers the call to a human agent or specific department.",
    whenToUse: "Use when the guest needs human assistance or for complex requests the AI can't handle.",
    example: "\"I'll transfer you to our reservations team. Please hold.\""
  },
  { 
    type: "end", 
    label: "End Call", 
    icon: <PhoneOff className="h-3 w-3" />, 
    color: "bg-red-500",
    description: "Ends the conversation with a closing message. Every flow path should end with this node.",
    whenToUse: "Use to gracefully close the conversation after completing the guest's request.",
    example: "\"Thank you for booking with us! Your confirmation number is 12345. Goodbye!\""
  },
];

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "";
  const date = new Date(dateStr);
  return date.toLocaleDateString("en-US", { 
    month: "short", 
    day: "numeric", 
    hour: "2-digit", 
    minute: "2-digit" 
  });
}

export default function FlowToolbar({ onSave, isSaving, showSimulator, onToggleSimulator }: FlowToolbarProps) {
  const { 
    addNode, 
    isDirty, 
    applyTemplate, 
    isLoading, 
    nodes,
    currentSource,
    currentVersionNumber,
    publishedVersionNumber,
    hasDraft,
    hasPublished,
    versions,
    publishFlow,
    discardDraft,
    revertToVersion,
    globalPrompt,
    setGlobalPrompt,
  } = useFlowStore();
  
  const [showAddMenu, setShowAddMenu] = useState(false);
  const [showTemplateMenu, setShowTemplateMenu] = useState(false);
  const [showVersionMenu, setShowVersionMenu] = useState(false);
  const [showPublishModal, setShowPublishModal] = useState(false);
  const [publishDescription, setPublishDescription] = useState("");
  const [isPublishing, setIsPublishing] = useState(false);
  const [showNodeInfo, setShowNodeInfo] = useState<NodeInfo | null>(null);
  const [showSettingsModal, setShowSettingsModal] = useState(false);
  const [tempGlobalPrompt, setTempGlobalPrompt] = useState("");

  const handleAddNode = (type: NodeType) => {
    const lastNode = nodes[nodes.length - 1];
    const position = lastNode 
      ? { x: lastNode.position.x, y: lastNode.position.y + 150 }
      : { x: 250, y: 100 };
    addNode(type, position);
    setShowAddMenu(false);
  };

  const handleApplyTemplate = (templateId: string) => {
    applyTemplate(templateId);
    setShowTemplateMenu(false);
  };

  const handlePublish = async () => {
    if (isDirty) {
      toast.error("Save your changes before publishing");
      return;
    }
    
    if (!hasDraft) {
      toast.error("No draft to publish. Save changes first.");
      return;
    }
    
    setIsPublishing(true);
    try {
      await publishFlow(publishDescription || undefined);
      toast.success(`Version ${currentVersionNumber} published successfully`);
      setShowPublishModal(false);
      setPublishDescription("");
    } catch (error: any) {
      const errorMessage = error?.message || "Failed to publish flow";
      if (errorMessage.includes("validation failed") || errorMessage.includes("errors")) {
        try {
          const parsed = JSON.parse(errorMessage.replace("Flow validation failed: ", ""));
          if (parsed.errors && Array.isArray(parsed.errors)) {
            toast.error(`Validation failed: ${parsed.errors.join(", ")}`);
          } else {
            toast.error(errorMessage);
          }
        } catch {
          toast.error(errorMessage);
        }
      } else {
        toast.error(errorMessage);
      }
    } finally {
      setIsPublishing(false);
    }
  };

  const handleDiscardDraft = async () => {
    if (!confirm("Are you sure you want to discard all draft changes? This will revert to the last published version.")) {
      return;
    }
    
    try {
      await discardDraft();
      toast.success("Draft discarded");
    } catch (error) {
      toast.error("Failed to discard draft");
    }
  };

  const handleRevert = async (versionNumber: number) => {
    if (!confirm(`Restore version ${versionNumber}? This will replace your current draft with that version's content.`)) {
      return;
    }
    
    try {
      await revertToVersion(versionNumber);
      toast.success(`Restored version ${versionNumber}`);
      setShowVersionMenu(false);
    } catch (error) {
      toast.error("Failed to restore version");
    }
  };

  const closeAllMenus = () => {
    setShowAddMenu(false);
    setShowTemplateMenu(false);
    setShowVersionMenu(false);
  };

  return (
    <>
      <div className="h-12 bg-[#141414] border-b border-gray-800 flex items-center justify-between px-4">
        <div className="flex items-center gap-2">
          <div className="relative">
            <button
              onClick={() => { closeAllMenus(); setShowAddMenu(!showAddMenu); }}
              className="flex items-center gap-1 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 rounded-lg text-sm font-medium transition"
            >
              <Plus className="h-4 w-4" />
              Add Node
              <ChevronDown className="h-3 w-3" />
            </button>
            
            {showAddMenu && (
              <div className="absolute top-full left-0 mt-1 w-64 bg-[#1a1a1a] border border-gray-700 rounded-lg shadow-xl z-50 py-1">
                <div className="px-3 py-1.5 text-xs text-gray-500 uppercase tracking-wider">Node Types</div>
                {nodeTypeConfig.map((config) => (
                  <div
                    key={config.type}
                    className="flex items-center hover:bg-gray-800 group"
                  >
                    <button
                      onClick={() => handleAddNode(config.type)}
                      className="flex-1 px-3 py-2 text-left text-sm text-gray-300 flex items-center gap-3"
                    >
                      <div className={`w-4 h-4 rounded flex items-center justify-center ${config.color}`}>
                        {config.icon}
                      </div>
                      {config.label}
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setShowAddMenu(false);
                        setShowNodeInfo(config);
                      }}
                      className="p-2 text-gray-500 hover:text-blue-400 opacity-0 group-hover:opacity-100 transition-opacity"
                      title={`Learn about ${config.label}`}
                    >
                      <Info className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="relative">
            <button
              onClick={() => { closeAllMenus(); setShowTemplateMenu(!showTemplateMenu); }}
              className="flex items-center gap-1 px-3 py-1.5 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm font-medium transition"
            >
              <Layout className="h-4 w-4" />
              Templates
              <ChevronDown className="h-3 w-3" />
            </button>
            
            {showTemplateMenu && (
              <div className="absolute top-full left-0 mt-1 w-72 bg-[#1a1a1a] border border-gray-700 rounded-lg shadow-xl z-50 py-1">
                <div className="px-3 py-1.5 text-xs text-gray-500 uppercase tracking-wider">Hotel Templates</div>
                {AVAILABLE_TEMPLATES.map((template) => (
                  <button
                    key={template.id}
                    onClick={() => handleApplyTemplate(template.id)}
                    disabled={isLoading}
                    className="w-full px-3 py-2 text-left hover:bg-gray-800 disabled:opacity-50"
                  >
                    <div className="text-sm text-white font-medium">
                      {template.name}
                    </div>
                    <div className="text-xs text-gray-400">
                      {template.description}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="h-6 w-px bg-gray-700 mx-2" />

          <button
            className="p-2 text-gray-400 hover:text-white rounded-lg hover:bg-gray-800 transition"
            title="Undo"
          >
            <Undo2 className="h-4 w-4" />
          </button>

          <button
            className="p-2 text-gray-400 hover:text-white rounded-lg hover:bg-gray-800 transition"
            title="Redo"
          >
            <Redo2 className="h-4 w-4" />
          </button>

          <div className="h-6 w-px bg-gray-700 mx-2" />

          {/* Version indicator and dropdown */}
          <div className="relative">
            <button
              onClick={() => { closeAllMenus(); setShowVersionMenu(!showVersionMenu); }}
              className="flex items-center gap-2 px-3 py-1.5 bg-gray-800 hover:bg-gray-700 rounded-lg text-sm transition"
            >
              <History className="h-4 w-4 text-gray-400" />
              <span className="text-gray-300">
                {currentSource === "draft" ? (
                  <>
                    <span className="text-yellow-500">Draft</span>
                    <span className="text-gray-500 ml-1">v{currentVersionNumber}</span>
                  </>
                ) : currentSource === "published" ? (
                  <>
                    <span className="text-green-500">Published</span>
                    <span className="text-gray-500 ml-1">v{publishedVersionNumber}</span>
                  </>
                ) : (
                  <span className="text-gray-400">No version</span>
                )}
              </span>
              <ChevronDown className="h-3 w-3 text-gray-400" />
            </button>

            {showVersionMenu && (
              <div className="absolute top-full left-0 mt-1 w-80 bg-[#1a1a1a] border border-gray-700 rounded-lg shadow-xl z-50 max-h-80 overflow-y-auto">
                <div className="px-3 py-2 border-b border-gray-700">
                  <div className="text-xs text-gray-500 uppercase tracking-wider">Version History</div>
                </div>
                
                {versions.length === 0 ? (
                  <div className="px-3 py-4 text-sm text-gray-500 text-center">
                    No versions yet. Save to create a draft.
                  </div>
                ) : (
                  versions.map((version) => (
                    <div
                      key={version.id}
                      className={`px-3 py-2 border-b border-gray-800 last:border-0 ${
                        version.version_number === currentVersionNumber ? "bg-gray-800/50" : ""
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          {version.status === "draft" ? (
                            <FileEdit className="h-4 w-4 text-yellow-500" />
                          ) : (
                            <CheckCircle2 className="h-4 w-4 text-green-500" />
                          )}
                          <span className="text-sm text-white">
                            Version {version.version_number}
                          </span>
                          {version.status === "draft" && (
                            <span className="px-1.5 py-0.5 text-xs bg-yellow-500/20 text-yellow-500 rounded">
                              Draft
                            </span>
                          )}
                          {version.version_number === publishedVersionNumber && version.status === "published" && (
                            <span className="px-1.5 py-0.5 text-xs bg-green-500/20 text-green-500 rounded">
                              Live
                            </span>
                          )}
                        </div>
                        
                        {version.status === "published" && version.version_number !== currentVersionNumber && (
                          <button
                            onClick={() => handleRevert(version.version_number)}
                            className="p-1 text-gray-400 hover:text-white hover:bg-gray-700 rounded"
                            title="Revert to this version"
                          >
                            <RotateCcw className="h-3.5 w-3.5" />
                          </button>
                        )}
                      </div>
                      
                      {version.description && (
                        <div className="text-xs text-gray-400 mt-1 ml-6">
                          {version.description}
                        </div>
                      )}
                      
                      <div className="text-xs text-gray-500 mt-1 ml-6">
                        {version.status === "draft" 
                          ? formatDate(version.created_at)
                          : formatDate(version.published_at)
                        }
                      </div>
                    </div>
                  ))
                )}
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Draft indicator */}
          {currentSource === "draft" && (
            <div className="flex items-center gap-1 px-2 py-1 bg-yellow-500/10 border border-yellow-500/30 rounded text-yellow-500 text-xs">
              <FileEdit className="h-3 w-3" />
              Editing Draft
            </div>
          )}
          
          {isDirty && (
            <span className="text-xs text-yellow-500">Unsaved changes</span>
          )}

          <button
            onClick={() => {
              setTempGlobalPrompt(globalPrompt);
              setShowSettingsModal(true);
            }}
            className="flex items-center gap-2 px-3 py-1.5 bg-gray-700 hover:bg-gray-600 text-white rounded-lg text-sm font-medium transition"
            title="Flow Settings"
          >
            <Settings className="h-4 w-4" />
            Settings
          </button>

          {onToggleSimulator && (
            <button
              onClick={onToggleSimulator}
              disabled={nodes.length === 0}
              className={`
                flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium transition
                ${showSimulator
                  ? "bg-cyan-600 hover:bg-cyan-700 text-white"
                  : nodes.length > 0
                    ? "bg-gray-700 hover:bg-gray-600 text-white"
                    : "bg-gray-800 text-gray-500 cursor-not-allowed"
                }
              `}
            >
              <FlaskConical className="h-4 w-4" />
              {showSimulator ? "Hide Test" : "Test"}
            </button>
          )}

          {/* Discard Draft button */}
          {hasDraft && hasPublished && (
            <button
              onClick={handleDiscardDraft}
              disabled={isLoading}
              className="flex items-center gap-1 px-3 py-1.5 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded-lg text-sm transition"
              title="Discard draft and revert to published version"
            >
              <Trash2 className="h-4 w-4" />
              Discard
            </button>
          )}

          {/* Save Draft button */}
          <button
            onClick={onSave}
            disabled={isSaving || !isDirty}
            className={`
              flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium transition
              ${isDirty
                ? "bg-gray-600 hover:bg-gray-500 text-white"
                : "bg-gray-700 text-gray-400 cursor-not-allowed"
              }
            `}
          >
            <Save className="h-4 w-4" />
            {isSaving ? "Saving..." : "Save Draft"}
          </button>

          {/* Publish button */}
          <button
            onClick={() => setShowPublishModal(true)}
            disabled={isDirty || !hasDraft || isLoading}
            className={`
              flex items-center gap-2 px-4 py-1.5 rounded-lg text-sm font-medium transition
              ${hasDraft && !isDirty
                ? "bg-green-600 hover:bg-green-700 text-white"
                : "bg-gray-700 text-gray-400 cursor-not-allowed"
              }
            `}
            title={isDirty ? "Save your changes first" : !hasDraft ? "No draft to publish" : "Publish draft"}
          >
            <Upload className="h-4 w-4" />
            Publish
          </button>
        </div>

        {(showAddMenu || showTemplateMenu || showVersionMenu) && (
          <div
            className="fixed inset-0 z-40"
            onClick={closeAllMenus}
          />
        )}
      </div>

      {/* Publish Modal */}
      {showPublishModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-[#1a1a1a] border border-gray-700 rounded-lg shadow-xl w-96 p-4">
            <h3 className="text-lg font-semibold text-white mb-4">Publish Flow</h3>
            
            <div className="mb-4">
              <label className="block text-sm text-gray-400 mb-1">
                Version Description (optional)
              </label>
              <textarea
                value={publishDescription}
                onChange={(e) => setPublishDescription(e.target.value)}
                placeholder="What changed in this version?"
                className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-700 rounded-lg text-white text-sm resize-none h-20"
              />
            </div>
            
            <div className="text-sm text-gray-400 mb-4">
              This will make version <span className="text-white font-medium">{currentVersionNumber}</span> live.
              {publishedVersionNumber > 0 && (
                <span> Previous version {publishedVersionNumber} will be archived but can be reverted.</span>
              )}
            </div>
            
            <div className="flex justify-end gap-2">
              <button
                onClick={() => {
                  setShowPublishModal(false);
                  setPublishDescription("");
                }}
                className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-lg text-sm"
              >
                Cancel
              </button>
              <button
                onClick={handlePublish}
                disabled={isPublishing}
                className="px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg text-sm font-medium flex items-center gap-2"
              >
                <Upload className="h-4 w-4" />
                {isPublishing ? "Publishing..." : "Publish Now"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Node Info Modal */}
      {showNodeInfo && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => setShowNodeInfo(null)}>
          <div 
            className="bg-[#1a1a1a] border border-gray-700 rounded-lg shadow-xl w-[420px] max-w-[90vw] overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="flex items-center justify-between p-4 border-b border-gray-700">
              <div className="flex items-center gap-3">
                <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${showNodeInfo.color}`}>
                  <div className="scale-125">
                    {showNodeInfo.icon}
                  </div>
                </div>
                <h3 className="text-lg font-semibold text-white">{showNodeInfo.label}</h3>
              </div>
              <button
                onClick={() => setShowNodeInfo(null)}
                className="p-1 text-gray-400 hover:text-white hover:bg-gray-700 rounded"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            
            {/* Content */}
            <div className="p-4 space-y-4">
              <div>
                <h4 className="text-sm font-medium text-gray-400 mb-1">What it does</h4>
                <p className="text-sm text-gray-200">{showNodeInfo.description}</p>
              </div>
              
              <div>
                <h4 className="text-sm font-medium text-gray-400 mb-1">When to use</h4>
                <p className="text-sm text-gray-200">{showNodeInfo.whenToUse}</p>
              </div>
              
              <div>
                <h4 className="text-sm font-medium text-gray-400 mb-1">Example</h4>
                <p className="text-sm text-gray-300 italic bg-gray-800/50 px-3 py-2 rounded-lg">
                  {showNodeInfo.example}
                </p>
              </div>
            </div>
            
            {/* Footer */}
            <div className="p-4 border-t border-gray-700 flex justify-between items-center">
              <button
                onClick={() => {
                  handleAddNode(showNodeInfo.type);
                  setShowNodeInfo(null);
                }}
                className={`px-4 py-2 ${showNodeInfo.color} hover:opacity-90 text-white rounded-lg text-sm font-medium flex items-center gap-2`}
              >
                <Plus className="h-4 w-4" />
                Add {showNodeInfo.label}
              </button>
              <button
                onClick={() => setShowNodeInfo(null)}
                className="px-4 py-2 text-gray-400 hover:text-white text-sm"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Settings Modal */}
      {showSettingsModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => setShowSettingsModal(false)}>
          <div 
            className="bg-[#1a1a1a] border border-gray-700 rounded-lg shadow-xl w-[500px] max-w-[90vw] overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="flex items-center justify-between p-4 border-b border-gray-700">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg flex items-center justify-center bg-gray-700">
                  <Settings className="h-4 w-4 text-gray-300" />
                </div>
                <h3 className="text-lg font-semibold text-white">Flow Settings</h3>
              </div>
              <button
                onClick={() => setShowSettingsModal(false)}
                className="p-1 text-gray-400 hover:text-white hover:bg-gray-700 rounded"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            
            {/* Content */}
            <div className="p-4 space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-2">
                  Global Prompt
                </label>
                <p className="text-xs text-gray-500 mb-2">
                  Add instructions that apply to the entire flow. These supplement the system prompt and affect AI behavior throughout the conversation.
                </p>
                <textarea
                  value={tempGlobalPrompt}
                  onChange={(e) => setTempGlobalPrompt(e.target.value)}
                  placeholder="Example: Always spell out guest names letter by letter for confirmation. Use formal language throughout the conversation."
                  className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-700 rounded-lg text-white text-sm resize-none h-32 focus:border-blue-500 focus:outline-none"
                />
              </div>
            </div>
            
            {/* Footer */}
            <div className="p-4 border-t border-gray-700 flex justify-end gap-2">
              <button
                onClick={() => setShowSettingsModal(false)}
                className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-lg text-sm"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  setGlobalPrompt(tempGlobalPrompt);
                  setShowSettingsModal(false);
                  toast.success("Flow settings updated");
                }}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium"
              >
                Save Settings
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
