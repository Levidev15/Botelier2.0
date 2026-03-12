"use client";

import React from "react";

interface DashboardWidgetProps {
  title: string;
  children: React.ReactNode;
  className?: string;
  span?: 1 | 2 | 3 | 4;
}

export default function DashboardWidget({ title, children, className = "", span = 1 }: DashboardWidgetProps) {
  const colSpan =
    span === 4
      ? "col-span-1 sm:col-span-2 lg:col-span-4"
      : span === 3
        ? "col-span-1 sm:col-span-2 lg:col-span-3"
        : span === 2
          ? "col-span-1 sm:col-span-2"
          : "col-span-1";

  return (
    <div className={`bg-[#1a1a1a] border border-gray-800 rounded-xl p-5 ${colSpan} ${className}`}>
      <h3 className="text-sm font-medium text-gray-400 mb-3">{title}</h3>
      {children}
    </div>
  );
}
