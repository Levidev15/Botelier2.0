"use client";

import { useCallback, useEffect, useState } from "react";
import { ArrowDown, ArrowUp, RotateCcw, Save } from "lucide-react";
import { useAccountContext } from "@/lib/auth/useAccountContext";
import { useAuthToken } from "@/lib/auth/useAuthToken";
import { usePagePermission, AccessDeniedPage } from "@/components/ui/PermissionGate";
import { usePermissions } from "@/lib/auth/usePermissions";
import { notify } from "@/lib/notifications";

interface PageField {
  key: string;
  label: string;
  editable: boolean;
  visible?: boolean;
}
interface PageSection {
  id: string;
  title: string;
  fields: PageField[];
}
interface PageDesign {
  branding: {
    logo_url: string;
    primary_color: string;
    accent_color: string;
    heading: string;
    subheading: string;
  };
  sections: PageSection[];
  footer: {
    privacy_url: string;
    terms_url: string;
    show_powered_by: boolean;
  };
}

interface PropertyOption {
  id: string;
  name: string;
}

const CARD_KEYS = ["card_holder", "card_number", "card_expiry", "card_cvv"];

export default function PaymentPageDesigner() {
  const { hasAccess, loading: permLoading } = usePagePermission("integrations", "view");
  const { can, isPlatformAdmin } = usePermissions();
  const { accountId } = useAccountContext();
  const { authFetch } = useAuthToken();

  const [properties, setProperties] = useState<PropertyOption[]>([]);
  const [propertyId, setPropertyId] = useState<string>("");
  const [design, setDesign] = useState<PageDesign | null>(null);
  const [isCustom, setIsCustom] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const canEdit = isPlatformAdmin || can("integrations", "manage");

  useEffect(() => {
    if (!accountId) return;
    authFetch(`/api/properties?account_id=${accountId}`)
      .then((r) => (r.ok ? r.json() : { properties: [] }))
      .then((d) => setProperties(d.properties || []))
      .catch(() => setProperties([]));
  }, [accountId, authFetch]);

  const fetchDesign = useCallback(async () => {
    if (!accountId) return;
    setLoading(true);
    try {
      const url = `/api/payment-pages?account_id=${accountId}${
        propertyId ? `&property_id=${propertyId}` : ""
      }`;
      const res = await authFetch(url);
      if (res.ok) {
        const data = await res.json();
        setDesign(data.design);
        setIsCustom(!!data.is_custom);
      }
    } catch {
      notify.error("Could not load the payment page design.");
    } finally {
      setLoading(false);
    }
  }, [accountId, propertyId, authFetch]);

  useEffect(() => {
    fetchDesign();
  }, [fetchDesign]);

  const handleSave = async () => {
    if (!accountId || !design) return;
    setSaving(true);
    try {
      const url = `/api/payment-pages?account_id=${accountId}${
        propertyId ? `&property_id=${propertyId}` : ""
      }`;
      const res = await authFetch(url, {
        method: "PUT",
        body: JSON.stringify({ design }),
      });
      if (res.ok) {
        setIsCustom(true);
        notify.success("Payment page design saved.");
      } else {
        notify.error("Failed to save the design.");
      }
    } catch {
      notify.error("Failed to save the design.");
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async () => {
    if (!accountId) return;
    setSaving(true);
    try {
      const url = `/api/payment-pages?account_id=${accountId}${
        propertyId ? `&property_id=${propertyId}` : ""
      }`;
      const res = await authFetch(url, { method: "DELETE" });
      if (res.ok) {
        notify.success("Reset to the default design.");
        await fetchDesign();
      }
    } finally {
      setSaving(false);
    }
  };

  const patchBranding = (key: keyof PageDesign["branding"], value: string) => {
    if (!design) return;
    setDesign({ ...design, branding: { ...design.branding, [key]: value } });
  };
  const patchFooter = (key: keyof PageDesign["footer"], value: any) => {
    if (!design) return;
    setDesign({ ...design, footer: { ...design.footer, [key]: value } });
  };
  const patchField = (sIdx: number, fIdx: number, patch: Partial<PageField>) => {
    if (!design) return;
    const sections = design.sections.map((s, i) => {
      if (i !== sIdx) return s;
      const fields = s.fields.map((f, j) => (j === fIdx ? { ...f, ...patch } : f));
      return { ...s, fields };
    });
    setDesign({ ...design, sections });
  };
  const moveField = (sIdx: number, fIdx: number, dir: -1 | 1) => {
    if (!design) return;
    const sections = design.sections.map((s, i) => {
      if (i !== sIdx) return s;
      const fields = [...s.fields];
      const target = fIdx + dir;
      if (target < 0 || target >= fields.length) return s;
      [fields[fIdx], fields[target]] = [fields[target], fields[fIdx]];
      return { ...s, fields };
    });
    setDesign({ ...design, sections });
  };
  const patchSectionTitle = (sIdx: number, title: string) => {
    if (!design) return;
    const sections = design.sections.map((s, i) => (i === sIdx ? { ...s, title } : s));
    setDesign({ ...design, sections });
  };
  const moveSection = (sIdx: number, dir: -1 | 1) => {
    if (!design) return;
    const target = sIdx + dir;
    if (target < 0 || target >= design.sections.length) return;
    const sections = [...design.sections];
    [sections[sIdx], sections[target]] = [sections[target], sections[sIdx]];
    setDesign({ ...design, sections });
  };

  if (permLoading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="animate-spin h-6 w-6 border-2 border-blue-500 border-t-transparent rounded-full" />
      </div>
    );
  }
  if (!hasAccess) {
    return <AccessDeniedPage message="You don't have permission to design the payment page." />;
  }

  return (
    <div className="p-8 max-w-6xl">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">Payment Page Designer</h1>
          <p className="text-sm text-gray-400 mt-1">
            Design the secure review &amp; pay page callers see. Card fields are always
            secure and are never stored by Botelier.
          </p>
        </div>
        {canEdit && (
          <div className="flex gap-2">
            <button
              onClick={handleReset}
              disabled={saving || !isCustom}
              className="flex items-center gap-2 px-3 py-2 text-sm rounded-lg border border-gray-700 hover:bg-[#1a1a1a] disabled:opacity-40"
            >
              <RotateCcw className="h-4 w-4" /> Reset to default
            </button>
            <button
              onClick={handleSave}
              disabled={saving || !design}
              className="flex items-center gap-2 px-4 py-2 text-sm rounded-lg bg-blue-600 hover:bg-blue-500 disabled:opacity-40"
            >
              <Save className="h-4 w-4" /> {saving ? "Saving…" : "Save design"}
            </button>
          </div>
        )}
      </div>

      <div className="mb-6">
        <label className="block text-sm font-medium text-gray-300 mb-2">Property</label>
        <select
          value={propertyId}
          onChange={(e) => setPropertyId(e.target.value)}
          className="w-full max-w-sm px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
        >
          <option value="">Account default (all properties)</option>
          {properties.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        <p className="text-xs text-gray-500 mt-1">
          {isCustom
            ? "This scope has a custom design."
            : "Showing the default design. Save to customize this scope."}
        </p>
      </div>

      {loading || !design ? (
        <div className="text-sm text-gray-400">Loading design…</div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Editor */}
          <div className="space-y-6">
            <div className="bg-[#141414] border border-gray-800 rounded-lg p-6">
              <h2 className="text-lg font-semibold mb-4">Branding</h2>
              <div className="space-y-4">
                <TextInput label="Logo URL" value={design.branding.logo_url} onChange={(v) => patchBranding("logo_url", v)} disabled={!canEdit} />
                <TextInput label="Heading" value={design.branding.heading} onChange={(v) => patchBranding("heading", v)} disabled={!canEdit} />
                <TextInput label="Subheading" value={design.branding.subheading} onChange={(v) => patchBranding("subheading", v)} disabled={!canEdit} />
                <div className="grid grid-cols-2 gap-4">
                  <ColorInput label="Primary color" value={design.branding.primary_color} onChange={(v) => patchBranding("primary_color", v)} disabled={!canEdit} />
                  <ColorInput label="Accent color" value={design.branding.accent_color} onChange={(v) => patchBranding("accent_color", v)} disabled={!canEdit} />
                </div>
              </div>
            </div>

            {design.sections.map((section, sIdx) => (
              <div key={section.id} className="bg-[#141414] border border-gray-800 rounded-lg p-6">
                <div className="flex items-center gap-2 mb-4">
                  <div className="flex flex-col">
                    <button onClick={() => moveSection(sIdx, -1)} disabled={!canEdit || sIdx === 0} className="text-gray-500 hover:text-white disabled:opacity-30" title="Move section up">
                      <ArrowUp className="h-3.5 w-3.5" />
                    </button>
                    <button onClick={() => moveSection(sIdx, 1)} disabled={!canEdit || sIdx === design.sections.length - 1} className="text-gray-500 hover:text-white disabled:opacity-30" title="Move section down">
                      <ArrowDown className="h-3.5 w-3.5" />
                    </button>
                  </div>
                  <input
                    value={section.title}
                    onChange={(e) => patchSectionTitle(sIdx, e.target.value)}
                    disabled={!canEdit}
                    className="text-lg font-semibold bg-transparent border-b border-transparent hover:border-gray-700 focus:border-blue-600 focus:outline-none w-full"
                  />
                </div>
                <div className="space-y-2">
                  {section.fields.map((field, fIdx) => {
                    const isCard = CARD_KEYS.includes(field.key);
                    const isVisible = isCard ? true : field.visible !== false;
                    return (
                      <div key={field.key} className={`flex items-center gap-2 bg-[#0a0a0a] border border-gray-800 rounded-lg px-3 py-2 ${!isVisible ? "opacity-50" : ""}`}>
                        <div className="flex flex-col">
                          <button onClick={() => moveField(sIdx, fIdx, -1)} disabled={!canEdit || fIdx === 0} className="text-gray-500 hover:text-white disabled:opacity-30">
                            <ArrowUp className="h-3 w-3" />
                          </button>
                          <button onClick={() => moveField(sIdx, fIdx, 1)} disabled={!canEdit || fIdx === section.fields.length - 1} className="text-gray-500 hover:text-white disabled:opacity-30">
                            <ArrowDown className="h-3 w-3" />
                          </button>
                        </div>
                        <input
                          value={field.label}
                          onChange={(e) => patchField(sIdx, fIdx, { label: e.target.value })}
                          disabled={!canEdit}
                          className="flex-1 bg-transparent text-sm focus:outline-none"
                        />
                        <span className="text-xs text-gray-600 font-mono">{field.key}</span>
                        <label className="flex items-center gap-1 text-xs text-gray-400 whitespace-nowrap" title={isCard ? "Card fields are always shown" : "Show this field on the page"}>
                          <input
                            type="checkbox"
                            checked={isVisible}
                            disabled={!canEdit || isCard}
                            onChange={(e) => patchField(sIdx, fIdx, { visible: e.target.checked })}
                          />
                          visible
                        </label>
                        <label className="flex items-center gap-1 text-xs text-gray-400 whitespace-nowrap">
                          <input
                            type="checkbox"
                            checked={isCard ? true : field.editable}
                            disabled={!canEdit || isCard}
                            onChange={(e) => patchField(sIdx, fIdx, { editable: e.target.checked })}
                          />
                          editable
                        </label>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}

            <div className="bg-[#141414] border border-gray-800 rounded-lg p-6">
              <h2 className="text-lg font-semibold mb-4">Footer</h2>
              <div className="space-y-4">
                <TextInput label="Privacy Policy URL" value={design.footer.privacy_url} onChange={(v) => patchFooter("privacy_url", v)} disabled={!canEdit} />
                <TextInput label="Terms URL" value={design.footer.terms_url} onChange={(v) => patchFooter("terms_url", v)} disabled={!canEdit} />
                <label className="flex items-center gap-2 text-sm text-gray-300">
                  <input
                    type="checkbox"
                    checked={design.footer.show_powered_by}
                    disabled={!canEdit}
                    onChange={(e) => patchFooter("show_powered_by", e.target.checked)}
                  />
                  Show &ldquo;Powered by Botelier&rdquo;
                </label>
              </div>
            </div>
          </div>

          {/* Preview */}
          <div className="lg:sticky lg:top-6 self-start">
            <PreviewCard design={design} />
          </div>
        </div>
      )}
    </div>
  );
}

function TextInput({ label, value, onChange, disabled }: { label: string; value: string; onChange: (v: string) => void; disabled?: boolean }) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-300 mb-2">{label}</label>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        className="w-full px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600 disabled:opacity-50"
      />
    </div>
  );
}

function ColorInput({ label, value, onChange, disabled }: { label: string; value: string; onChange: (v: string) => void; disabled?: boolean }) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-300 mb-2">{label}</label>
      <div className="flex items-center gap-2">
        <input type="color" value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled} className="h-9 w-12 bg-transparent border border-gray-800 rounded" />
        <input type="text" value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled} className="flex-1 px-3 py-2 bg-[#0a0a0a] border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-600 disabled:opacity-50" />
      </div>
    </div>
  );
}

function PreviewCard({ design }: { design: PageDesign }) {
  const { branding, sections, footer } = design;
  return (
    <div className="rounded-2xl overflow-hidden shadow-2xl bg-white text-gray-900">
      <div style={{ background: branding.primary_color }} className="text-white p-6">
        {branding.logo_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={branding.logo_url} alt="logo" className="max-h-10 mb-3" />
        ) : null}
        <div className="text-xl font-semibold">{branding.heading || "Review & Pay"}</div>
        <div className="text-sm opacity-80">{branding.subheading}</div>
      </div>
      <div className="p-6 space-y-5">
        {sections.map((s) => (
          <div key={s.id}>
            <div className="text-xs uppercase tracking-wide text-gray-500 mb-2">{s.title}</div>
            <div className="grid grid-cols-2 gap-2">
              {s.fields.filter((f) => CARD_KEYS.includes(f.key) || f.visible !== false).map((f) => (
                <div key={f.key} className="flex flex-col">
                  <span className="text-[11px] text-gray-500">{f.label}</span>
                  <div className={`h-8 rounded border px-2 text-sm flex items-center ${f.editable && !CARD_KEYS.includes(f.key) ? "bg-white border-gray-300" : CARD_KEYS.includes(f.key) ? "bg-white border-gray-300" : "bg-gray-100 border-gray-200 text-gray-400"}`}>
                    {CARD_KEYS.includes(f.key) ? "" : "—"}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
        <button style={{ background: branding.accent_color }} className="w-full py-3 rounded-lg text-white font-semibold">
          Confirm &amp; Pay
        </button>
        <p className="text-[11px] text-gray-500 text-center">
          Your card is sent securely to the hotel&rsquo;s payment system.
        </p>
      </div>
      <div className="text-center p-4 text-[11px] text-gray-400 border-t">
        <div className="space-x-3">
          {footer.privacy_url && <span className="underline">Privacy Policy</span>}
          {footer.terms_url && <span className="underline">Terms</span>}
        </div>
        {footer.show_powered_by && <div className="mt-1">Powered by Botelier</div>}
      </div>
    </div>
  );
}
