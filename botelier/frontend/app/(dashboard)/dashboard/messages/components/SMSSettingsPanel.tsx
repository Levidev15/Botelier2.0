"use client";

import {
  X, Plus, Trash2, Edit2, Volume2, VolumeX,
} from "lucide-react";
import {
  SMSTemplate,
  NotificationSettings,
} from "../hooks/useSMSData";

interface Props {
  settingsTab: "notifications" | "templates";
  setSettingsTab: (v: "notifications" | "templates") => void;
  onClose: () => void;

  templates: SMSTemplate[];
  editingTemplate: SMSTemplate | null;
  setEditingTemplate: (t: SMSTemplate | null) => void;
  newTemplate: { name: string; content: string; category: string };
  setNewTemplate: (fn: (prev: { name: string; content: string; category: string }) => { name: string; content: string; category: string }) => void;
  showNewTemplate: boolean;
  setShowNewTemplate: (v: boolean) => void;
  onSaveTemplate: () => void;
  onUpdateTemplate: (t: SMSTemplate) => void;
  onDeleteTemplate: (id: string) => void;

  notifSettings: NotificationSettings;
  setNotifSettings: (fn: (prev: NotificationSettings) => NotificationSettings) => void;
  savingSettings: boolean;
  onSaveNotifSettings: () => void;
  onPreviewSound: () => void;
}

export function SMSSettingsPanel({
  settingsTab, setSettingsTab, onClose,
  templates, editingTemplate, setEditingTemplate,
  newTemplate, setNewTemplate, showNewTemplate, setShowNewTemplate,
  onSaveTemplate, onUpdateTemplate, onDeleteTemplate,
  notifSettings, setNotifSettings, savingSettings,
  onSaveNotifSettings, onPreviewSound,
}: Props) {
  return (
    <>
      <div className="fixed inset-0 bg-black/40 z-40" onClick={onClose} />
      <div className="fixed right-0 top-0 bottom-0 w-[420px] bg-[#111111] border-l border-gray-800 z-50 flex flex-col shadow-2xl">

        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-gray-800 flex-shrink-0">
          <h2 className="text-lg font-semibold text-white">Messages Settings</h2>
          <button onClick={onClose} className="p-1 text-gray-400 hover:text-white">
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-gray-800 flex-shrink-0">
          <button
            onClick={() => setSettingsTab("templates")}
            className={`flex-1 py-2.5 text-xs font-medium transition-colors ${
              settingsTab === "templates"
                ? "text-indigo-400 border-b-2 border-indigo-400"
                : "text-gray-500 hover:text-gray-300"
            }`}
          >
            Templates
          </button>
          <button
            onClick={() => setSettingsTab("notifications")}
            className={`flex-1 py-2.5 text-xs font-medium transition-colors ${
              settingsTab === "notifications"
                ? "text-indigo-400 border-b-2 border-indigo-400"
                : "text-gray-500 hover:text-gray-300"
            }`}
          >
            Notifications
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4">

          {/* Templates tab */}
          {settingsTab === "templates" && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <span className="text-sm font-medium text-white">Canned Responses</span>
                  <p className="text-[11px] text-gray-500 mt-0.5">
                    Use {"{{customer_number}}"}, {"{{date}}"}, {"{{time}}"} as variables
                  </p>
                </div>
                <button
                  onClick={() => setShowNewTemplate(!showNewTemplate)}
                  className="flex items-center gap-1 px-2.5 py-1 bg-indigo-600/10 hover:bg-indigo-600/20 text-indigo-400 rounded-lg text-xs transition-colors"
                >
                  <Plus className="h-3 w-3" />
                  New
                </button>
              </div>

              {showNewTemplate && (
                <div className="p-3 bg-[#1a1a1a] border border-gray-700 rounded-lg space-y-2">
                  <input
                    type="text"
                    value={newTemplate.name}
                    onChange={(e) => setNewTemplate(p => ({ ...p, name: e.target.value }))}
                    placeholder="Template name"
                    className="w-full px-3 py-1.5 bg-[#0a0a0a] border border-gray-700 rounded-lg text-xs text-white placeholder-gray-500 focus:outline-none focus:border-indigo-500"
                  />
                  <input
                    type="text"
                    value={newTemplate.category}
                    onChange={(e) => setNewTemplate(p => ({ ...p, category: e.target.value }))}
                    placeholder="Category (optional)"
                    className="w-full px-3 py-1.5 bg-[#0a0a0a] border border-gray-700 rounded-lg text-xs text-white placeholder-gray-500 focus:outline-none focus:border-indigo-500"
                  />
                  <textarea
                    value={newTemplate.content}
                    onChange={(e) => setNewTemplate(p => ({ ...p, content: e.target.value }))}
                    placeholder="Message content..."
                    rows={3}
                    className="w-full px-3 py-1.5 bg-[#0a0a0a] border border-gray-700 rounded-lg text-xs text-white placeholder-gray-500 focus:outline-none focus:border-indigo-500 resize-none"
                  />
                  <div className="flex gap-2">
                    <button
                      onClick={onSaveTemplate}
                      disabled={!newTemplate.name.trim() || !newTemplate.content.trim()}
                      className="px-3 py-1 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs disabled:opacity-50"
                    >
                      Save
                    </button>
                    <button
                      onClick={() => { setShowNewTemplate(false); setNewTemplate(() => ({ name: "", content: "", category: "" })); }}
                      className="px-3 py-1 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded-lg text-xs"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}

              {templates.length === 0 ? (
                <div className="py-8 text-center text-gray-500 text-xs">
                  No templates yet. Click "New" to create one.
                </div>
              ) : (
                <div className="space-y-2">
                  {templates.map((t) => (
                    <div key={t.id} className="p-3 bg-[#1a1a1a] border border-gray-700 rounded-lg">
                      {editingTemplate?.id === t.id ? (
                        <div className="space-y-2">
                          <input
                            type="text"
                            value={editingTemplate.name}
                            onChange={(e) => setEditingTemplate({ ...editingTemplate, name: e.target.value })}
                            className="w-full px-3 py-1.5 bg-[#0a0a0a] border border-gray-700 rounded-lg text-xs text-white focus:outline-none focus:border-indigo-500"
                          />
                          <input
                            type="text"
                            value={editingTemplate.category || ""}
                            onChange={(e) => setEditingTemplate({ ...editingTemplate, category: e.target.value || null })}
                            placeholder="Category"
                            className="w-full px-3 py-1.5 bg-[#0a0a0a] border border-gray-700 rounded-lg text-xs text-white placeholder-gray-500 focus:outline-none focus:border-indigo-500"
                          />
                          <textarea
                            value={editingTemplate.content}
                            onChange={(e) => setEditingTemplate({ ...editingTemplate, content: e.target.value })}
                            rows={3}
                            className="w-full px-3 py-1.5 bg-[#0a0a0a] border border-gray-700 rounded-lg text-xs text-white focus:outline-none focus:border-indigo-500 resize-none"
                          />
                          <div className="flex gap-2">
                            <button
                              onClick={() => onUpdateTemplate(editingTemplate)}
                              className="px-3 py-1 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs"
                            >
                              Save
                            </button>
                            <button
                              onClick={() => setEditingTemplate(null)}
                              className="px-3 py-1 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded-lg text-xs"
                            >
                              Cancel
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div className="flex items-start justify-between gap-2">
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              <span className="text-xs font-medium text-white">{t.name}</span>
                              {t.category && (
                                <span className="text-[10px] px-1.5 py-0.5 bg-gray-700 text-gray-400 rounded">
                                  {t.category}
                                </span>
                              )}
                            </div>
                            <p className="text-[11px] text-gray-400 mt-1 line-clamp-2">{t.content}</p>
                          </div>
                          <div className="flex items-center gap-1 flex-shrink-0">
                            <button
                              onClick={() => setEditingTemplate({ ...t })}
                              className="p-1 text-gray-500 hover:text-indigo-400 transition-colors"
                            >
                              <Edit2 className="h-3 w-3" />
                            </button>
                            <button
                              onClick={() => onDeleteTemplate(t.id)}
                              className="p-1 text-gray-500 hover:text-red-400 transition-colors"
                            >
                              <Trash2 className="h-3 w-3" />
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Notifications tab */}
          {settingsTab === "notifications" && (
            <div className="space-y-5">
              <div>
                <span className="text-sm font-medium text-white">Notification Preferences</span>
                <p className="text-[11px] text-gray-500 mt-0.5">
                  Real-time alerts powered by a live connection — no polling.
                </p>
              </div>

              {/* Sound toggle */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  {notifSettings.sound_enabled
                    ? <Volume2 className="h-4 w-4 text-indigo-400" />
                    : <VolumeX className="h-4 w-4 text-gray-500" />
                  }
                  <span className="text-xs text-white">Sound notifications</span>
                </div>
                <button
                  onClick={() => setNotifSettings(p => ({ ...p, sound_enabled: !p.sound_enabled }))}
                  className={`w-10 h-5 rounded-full transition-colors relative ${
                    notifSettings.sound_enabled ? "bg-indigo-600" : "bg-gray-700"
                  }`}
                >
                  <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
                    notifSettings.sound_enabled ? "translate-x-5" : "translate-x-0.5"
                  }`} />
                </button>
              </div>

              {notifSettings.sound_enabled && (
                <div>
                  <label className="text-[11px] text-gray-400 block mb-1">Sound type</label>
                  <select
                    value={notifSettings.sound_type}
                    onChange={(e) => setNotifSettings(p => ({ ...p, sound_type: e.target.value }))}
                    className="w-full px-3 py-1.5 bg-[#1a1a1a] border border-gray-700 rounded-lg text-xs text-white focus:outline-none focus:border-indigo-500"
                  >
                    <option value="chime">Chime</option>
                    <option value="bell">Bell</option>
                    <option value="ding">Ding</option>
                  </select>
                  <button
                    onClick={onPreviewSound}
                    className="mt-2 text-xs text-indigo-400 hover:text-indigo-300 underline"
                  >
                    Preview sound
                  </button>
                </div>
              )}

              {/* Visual toggle */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-xs text-white">Visual toast notifications</span>
                </div>
                <button
                  onClick={() => setNotifSettings(p => ({ ...p, visual_enabled: !p.visual_enabled }))}
                  className={`w-10 h-5 rounded-full transition-colors relative ${
                    notifSettings.visual_enabled ? "bg-indigo-600" : "bg-gray-700"
                  }`}
                >
                  <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
                    notifSettings.visual_enabled ? "translate-x-5" : "translate-x-0.5"
                  }`} />
                </button>
              </div>

              <div>
                <label className="text-[11px] text-gray-400 block mb-1">
                  Notify when unread count reaches
                </label>
                <input
                  type="number"
                  min={1}
                  max={99}
                  value={notifSettings.threshold}
                  onChange={(e) => setNotifSettings(p => ({ ...p, threshold: parseInt(e.target.value) || 1 }))}
                  className="w-20 px-3 py-1.5 bg-[#1a1a1a] border border-gray-700 rounded-lg text-xs text-white focus:outline-none focus:border-indigo-500"
                />
              </div>

              <button
                onClick={onSaveNotifSettings}
                disabled={savingSettings}
                className="w-full py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-medium transition-colors disabled:opacity-50"
              >
                {savingSettings ? "Saving..." : "Save Settings"}
              </button>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
