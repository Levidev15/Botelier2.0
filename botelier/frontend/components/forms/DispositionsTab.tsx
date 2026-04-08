"use client";

import { useState, useEffect } from "react";
import { Plus, Edit2, Trash2, GripVertical, Check, X } from "lucide-react";
import { notify, confirmAction } from "@/lib/notifications";
import { useAuthToken } from "@/lib/auth/useAuthToken";

interface Disposition {
  id: string;
  assistant_id: string;
  name: string;
  description: string | null;
  color: string;
  display_order: number;
  is_active: boolean;
}

interface DispositionsTabProps {
  assistantId: string;
  accountId: string;
}

const COLOR_OPTIONS = [
  "#6366f1", // Indigo
  "#8b5cf6", // Violet
  "#ec4899", // Pink
  "#ef4444", // Red
  "#f97316", // Orange
  "#eab308", // Yellow
  "#22c55e", // Green
  "#14b8a6", // Teal
  "#3b82f6", // Blue
  "#6b7280", // Gray
];

export default function DispositionsTab({ assistantId, accountId }: DispositionsTabProps) {
  const [dispositions, setDispositions] = useState<Disposition[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [formData, setFormData] = useState({
    name: "",
    description: "",
    color: "#6366f1",
    is_active: true,
  });
  const { authFetch } = useAuthToken();

  useEffect(() => {
    fetchDispositions();
  }, [assistantId, accountId]);

  const fetchDispositions = async () => {
    try {
      const response = await authFetch(
        `/api/assistants/${assistantId}/dispositions?account_id=${accountId}`
      );
      if (response.ok) {
        const data = await response.json();
        setDispositions(data);
      }
    } catch (error) {
      console.error("Error fetching dispositions:", error);
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    try {
      const url = editingId
        ? `/api/assistants/${assistantId}/dispositions/${editingId}?account_id=${accountId}`
        : `/api/assistants/${assistantId}/dispositions?account_id=${accountId}`;
      
      const response = await authFetch(url, {
        method: editingId ? "PATCH" : "POST",
        body: JSON.stringify(formData),
      });

      if (response.ok) {
        notify.success(editingId ? "Disposition updated" : "Disposition created");
        fetchDispositions();
        resetForm();
      } else {
        notify.error("Failed to save disposition");
      }
    } catch (error) {
      notify.error("Error saving disposition");
    }
  };

  const handleDelete = async (id: string) => {
    const confirmed = await confirmAction("Are you sure you want to delete this disposition?", {
      confirmText: "Delete",
    });
    if (!confirmed) return;
    
    try {
      const response = await authFetch(
        `/api/assistants/${assistantId}/dispositions/${id}?account_id=${accountId}`,
        { method: "DELETE" }
      );

      if (response.ok) {
        notify.success("Disposition deleted");
        fetchDispositions();
      } else {
        notify.error("Failed to delete disposition");
      }
    } catch (error) {
      notify.error("Error deleting disposition");
    }
  };

  const handleEdit = (disposition: Disposition) => {
    setEditingId(disposition.id);
    setFormData({
      name: disposition.name,
      description: disposition.description || "",
      color: disposition.color,
      is_active: disposition.is_active,
    });
    setShowForm(true);
  };

  const resetForm = () => {
    setShowForm(false);
    setEditingId(null);
    setFormData({
      name: "",
      description: "",
      color: "#6366f1",
      is_active: true,
    });
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-indigo-500"></div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-medium text-white">Call Dispositions</h3>
          <p className="text-sm text-gray-400 mt-1">
            Define custom dispositions that the AI will choose from based on call outcomes
          </p>
        </div>
        {!showForm && (
          <button
            onClick={() => setShowForm(true)}
            className="flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors text-sm"
          >
            <Plus className="h-4 w-4" />
            Add Disposition
          </button>
        )}
      </div>

      {showForm && (
        <form onSubmit={handleSubmit} className="bg-gray-800 rounded-lg p-4 border border-gray-700 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">Name</label>
              <input
                type="text"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                placeholder="e.g., Reservation Made"
                className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">Color</label>
              <div className="flex gap-2 flex-wrap">
                {COLOR_OPTIONS.map((color) => (
                  <button
                    key={color}
                    type="button"
                    onClick={() => setFormData({ ...formData, color })}
                    className={`w-8 h-8 rounded-full border-2 transition-all ${
                      formData.color === color ? "border-white scale-110" : "border-transparent hover:scale-105"
                    }`}
                    style={{ backgroundColor: color }}
                  />
                ))}
              </div>
            </div>
          </div>
          
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">
              Description <span className="text-gray-500">(helps AI understand when to use this)</span>
            </label>
            <textarea
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              placeholder="e.g., Caller successfully booked a reservation during the call"
              rows={2}
              className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"
            />
          </div>

          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="is_active"
              checked={formData.is_active}
              onChange={(e) => setFormData({ ...formData, is_active: e.target.checked })}
              className="w-4 h-4 rounded border-gray-600 bg-gray-900 text-indigo-600 focus:ring-indigo-500"
            />
            <label htmlFor="is_active" className="text-sm text-gray-300">Active</label>
          </div>

          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={resetForm}
              className="px-4 py-2 text-gray-400 hover:text-white transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors"
            >
              {editingId ? "Update" : "Create"}
            </button>
          </div>
        </form>
      )}

      {dispositions.length === 0 && !showForm ? (
        <div className="text-center py-12 bg-gray-800/50 rounded-lg border border-gray-700 border-dashed">
          <p className="text-gray-400">No dispositions configured yet</p>
          <p className="text-sm text-gray-500 mt-1">
            Add dispositions to track call outcomes and let AI categorize them automatically
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {dispositions.map((disposition) => (
            <div
              key={disposition.id}
              className={`flex items-center gap-3 p-3 bg-gray-800 rounded-lg border border-gray-700 group ${
                !disposition.is_active ? "opacity-50" : ""
              }`}
            >
              <GripVertical className="h-4 w-4 text-gray-600 cursor-grab" />
              <div
                className="w-3 h-3 rounded-full flex-shrink-0"
                style={{ backgroundColor: disposition.color }}
              />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-white font-medium">{disposition.name}</span>
                  {!disposition.is_active && (
                    <span className="text-xs text-gray-500 bg-gray-700 px-2 py-0.5 rounded">Inactive</span>
                  )}
                </div>
                {disposition.description && (
                  <p className="text-sm text-gray-400 truncate">{disposition.description}</p>
                )}
              </div>
              <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                <button
                  onClick={() => handleEdit(disposition)}
                  className="p-2 text-gray-400 hover:text-white hover:bg-gray-700 rounded-lg transition-colors"
                >
                  <Edit2 className="h-4 w-4" />
                </button>
                <button
                  onClick={() => handleDelete(disposition.id)}
                  className="p-2 text-gray-400 hover:text-red-400 hover:bg-gray-700 rounded-lg transition-colors"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
