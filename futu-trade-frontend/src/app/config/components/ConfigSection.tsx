// 配置分组组件

import React from "react";

interface ConfigSectionProps {
  id: string;
  title: string;
  icon: string;
  isOpen?: boolean;
  children: React.ReactNode;
}

export function ConfigSection({
  id,
  title,
  icon,
  isOpen = false,
  children,
}: ConfigSectionProps) {
  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      <button
        type="button"
        className="w-full flex items-center justify-between px-4 py-3 bg-gray-50 hover:bg-gray-100 transition-colors"
        data-accordion-target={`#${id}`}
        aria-expanded={isOpen}
        aria-controls={id}
      >
        <div className="flex items-center gap-2">
          <i className={`fas ${icon} text-gray-600`}></i>
          <span className="font-medium text-gray-900">{title}</span>
        </div>
        <i className="fas fa-chevron-down text-gray-400 transition-transform"></i>
      </button>

      <div
        id={id}
        className={`${isOpen ? "" : "hidden"} px-4 py-4 bg-white`}
        aria-labelledby={`${id}-heading`}
      >
        {children}
      </div>
    </div>
  );
}
