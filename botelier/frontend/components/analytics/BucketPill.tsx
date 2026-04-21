"use client";

// Task #129 — small clickable pill for one MECE partition bucket. Renders
// label, count, and % of total; optionally renders a horizontal mini stacked
// bar for sub-breakdowns (used by the Unresolved pill so the silent-caller
// vs dropped-pre-greeting split is visible at a glance instead of buried in
// a tooltip). Clicking the pill opens the existing CallDrilldownModal with
// the bucket token pre-applied — the trigger surface is the only thing
// changing here; the modal's row set still comes from `_bucket_predicate`.

export interface BucketPillSubSegment {
  key: string;
  label: string;
  count: number;
  color: string;
}

interface BucketPillProps {
  label: string;
  count: number;
  total: number;
  color: string;          // accent color (hex)
  bucketKey: string;      // canonical token forwarded to drilldown
  onClick?: (bucketKey: string, label: string) => void;
  subSegments?: BucketPillSubSegment[];
  tooltip?: string;
}

export default function BucketPill({
  label,
  count,
  total,
  color,
  bucketKey,
  onClick,
  subSegments,
  tooltip,
}: BucketPillProps) {
  const pct = total > 0 ? (count / total) * 100 : 0;
  const subTotal = subSegments?.reduce((s, x) => s + x.count, 0) ?? 0;
  const isClickable = typeof onClick === "function";

  return (
    <div
      onClick={isClickable ? () => onClick!(bucketKey, label) : undefined}
      title={tooltip}
      className={`bg-[#1a1a1a] border border-gray-800 rounded-xl p-4 transition-colors ${
        isClickable ? "cursor-pointer hover:border-gray-600 hover:bg-[#222]" : ""
      }`}
    >
      <div className="flex items-center gap-2 mb-1">
        <span
          className="w-2.5 h-2.5 rounded-sm flex-shrink-0"
          style={{ backgroundColor: color }}
        />
        <p className="text-xs text-gray-400 truncate flex-1">{label}</p>
      </div>
      <p className="text-xl font-bold text-gray-100">{count.toLocaleString()}</p>
      <p className="text-[11px] text-gray-500 mt-0.5">{pct.toFixed(1)}% of total</p>

      {subSegments && subSegments.length > 0 && subTotal > 0 && (
        <div className="mt-3 pt-3 border-t border-gray-800/80">
          <div
            className="h-1.5 w-full rounded-full overflow-hidden flex bg-gray-800"
            aria-label={`${label} sub-breakdown`}
          >
            {subSegments.map((s) => {
              if (s.count <= 0) return null;
              const w = (s.count / subTotal) * 100;
              return (
                <div
                  key={s.key}
                  style={{ width: `${w}%`, backgroundColor: s.color }}
                  title={`${s.label}: ${s.count}`}
                />
              );
            })}
          </div>
          <div className="mt-1.5 space-y-0.5">
            {subSegments.map((s) => (
              <div key={s.key} className="flex items-center justify-between text-[11px]">
                <span className="flex items-center gap-1.5 text-gray-400 truncate">
                  <span
                    className="w-1.5 h-1.5 rounded-full flex-shrink-0"
                    style={{ backgroundColor: s.color }}
                  />
                  {s.label}
                </span>
                <span className="text-gray-500 ml-1">{s.count}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
