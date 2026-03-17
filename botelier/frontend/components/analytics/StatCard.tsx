"use client";

interface StatCardProps {
  label: string;
  value: string | number;
  sub?: string;
  color?: string;
  onClick?: () => void;
}

export default function StatCard({ label, value, sub, color = "text-gray-100", onClick }: StatCardProps) {
  const isClickable = typeof onClick === "function";
  return (
    <div
      onClick={onClick}
      className={`bg-[#1a1a1a] border border-gray-800 rounded-xl p-5 transition-colors ${
        isClickable
          ? "cursor-pointer hover:border-gray-600 hover:bg-[#222]"
          : ""
      }`}
    >
      <p className="text-sm text-gray-400 mb-1">{label}</p>
      <p className={`text-2xl font-bold ${color}`}>{value}</p>
      {sub && <p className="text-xs text-gray-500 mt-1">{sub}</p>}
      {isClickable && (
        <p className="text-xs text-gray-600 mt-2">Click to view calls →</p>
      )}
    </div>
  );
}
