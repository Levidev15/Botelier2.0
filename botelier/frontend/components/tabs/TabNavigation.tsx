"use client";

import { useEffect, useState } from "react";

export interface Tab {
  id: string;
  label: string;
  icon?: React.ReactNode;
}

interface TabNavigationProps {
  tabs: Tab[];
  activeTab: string;
  onTabChange: (tabId: string) => void;
  sticky?: boolean;
  topOffset?: number;
}

export default function TabNavigation({
  tabs,
  activeTab,
  onTabChange,
  sticky = true,
  topOffset = 0,
}: TabNavigationProps) {
  return (
    <div
      className={`border-b border-gray-800 bg-[#0a0a0a] ${
        sticky ? "sticky z-20" : ""
      }`}
      style={sticky ? { top: `${topOffset}px` } : undefined}
    >
      <div className="px-8">
        <nav className="flex space-x-1 overflow-x-auto">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => onTabChange(tab.id)}
              className={`
                px-4 py-3 text-sm font-medium whitespace-nowrap transition-colors relative
                ${
                  activeTab === tab.id
                    ? "text-white"
                    : "text-gray-400 hover:text-gray-300"
                }
              `}
            >
              <div className="flex items-center space-x-2">
                {tab.icon && <span className="h-4 w-4">{tab.icon}</span>}
                <span>{tab.label}</span>
              </div>
              {activeTab === tab.id && (
                <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-blue-600" />
              )}
            </button>
          ))}
        </nav>
      </div>
    </div>
  );
}
