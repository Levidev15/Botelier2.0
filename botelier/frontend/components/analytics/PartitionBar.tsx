"use client";

// Task #129 — single horizontal stacked bar showing the 5 MECE partition
// buckets returned by GET /api/analytics/calls. Segment widths are computed
// from the same `*_count` keys the bucket pills use, so the bar and the
// pills below it can never disagree. Clicking a segment opens the existing
// drilldown modal pre-filtered to that bucket via the canonical token
// understood by `_bucket_predicate` on the backend.

export interface PartitionBarBucket {
  key: string;          // canonical bucket token (ai_handled, ended_early, missed, failed, unresolved)
  label: string;        // user-facing label
  count: number;
  color: string;        // tailwind bg color class fragment OR hex
}

interface PartitionBarProps {
  buckets: PartitionBarBucket[];
  total: number;
  onSegmentClick?: (bucketKey: string, label: string) => void;
}

export default function PartitionBar({ buckets, total, onSegmentClick }: PartitionBarProps) {
  // When total == 0 we render an empty rail so layout doesn't jump on first
  // load. We deliberately do NOT recompute total from segments — the API's
  // `total_calls` is the authoritative denominator and the partition is
  // designed to sum to it (`partition_integrity_ok`).
  const safeTotal = Math.max(1, total);
  const visibleBuckets = buckets.filter((b) => b.count > 0);

  return (
    <div className="bg-[#1a1a1a] border border-gray-800 rounded-xl p-5">
      <div className="flex items-baseline justify-between mb-3">
        <div>
          <h2 className="text-sm font-medium text-gray-300">Where did your calls go?</h2>
          <p className="text-xs text-gray-500 mt-0.5">
            Every call falls into exactly one bucket — segments sum to {total.toLocaleString()} total.
          </p>
        </div>
      </div>

      {total === 0 ? (
        <div className="h-10 rounded-lg bg-gray-800/40 flex items-center justify-center text-xs text-gray-500">
          No calls in this window
        </div>
      ) : (
        <>
          <div
            className="h-10 w-full rounded-lg overflow-hidden flex"
            role="img"
            aria-label="Call partition breakdown"
          >
            {visibleBuckets.map((b) => {
              const pct = (b.count / safeTotal) * 100;
              const showInline = pct >= 8;
              return (
                <button
                  key={b.key}
                  type="button"
                  onClick={() => onSegmentClick?.(b.key, b.label)}
                  style={{ width: `${pct}%`, backgroundColor: b.color }}
                  className="h-full flex items-center justify-center text-xs font-medium text-black/80 hover:brightness-110 transition-all border-r border-black/20 last:border-r-0"
                  title={`${b.label}: ${b.count.toLocaleString()} (${pct.toFixed(1)}%)`}
                >
                  {showInline && (
                    <span className="truncate px-1">
                      {b.count.toLocaleString()}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-400">
            {buckets.map((b) => {
              const pct = total > 0 ? (b.count / total) * 100 : 0;
              return (
                <div key={b.key} className="flex items-center gap-1.5">
                  <span
                    className="w-2.5 h-2.5 rounded-sm"
                    style={{ backgroundColor: b.color }}
                  />
                  <span>{b.label}</span>
                  <span className="text-gray-500">— {pct.toFixed(1)}%</span>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
