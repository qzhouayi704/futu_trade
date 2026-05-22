// 应用布局组件

"use client";

import { useState, useEffect } from "react";
import { Sidebar } from "./Sidebar";

interface AppLayoutProps {
  children: React.ReactNode;
}

export function AppLayout({ children }: AppLayoutProps) {
  const [mobileOpen, setMobileOpen] = useState(false);

  // 屏幕尺寸变化时自动关闭移动菜单
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 768px)");
    const handler = (e: MediaQueryListEvent) => {
      if (e.matches) setMobileOpen(false);
    };
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  // 移动端菜单打开时禁止body滚动
  useEffect(() => {
    if (mobileOpen) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => { document.body.style.overflow = ""; };
  }, [mobileOpen]);

  return (
    <div className="flex min-h-screen bg-background">
      {/* 移动端汉堡按钮 */}
      <button
        onClick={() => setMobileOpen(true)}
        className="fixed top-3 left-3 z-50 md:hidden flex items-center justify-center w-10 h-10 rounded-xl bg-card/80 backdrop-blur-lg border border-border shadow-lg active:scale-95 transition-transform"
        aria-label="打开菜单"
      >
        <svg className="w-5 h-5 text-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
        </svg>
      </button>

      {/* 移动端遮罩层 */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm md:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* 侧边栏：桌面端正常显示，移动端抽屉式弹出 */}
      <div
        className={`
          fixed inset-y-0 left-0 z-50 transition-transform duration-300 ease-out
          md:relative md:translate-x-0 md:z-auto
          ${mobileOpen ? "translate-x-0" : "-translate-x-full"}
        `}
      >
        <Sidebar onNavigate={() => setMobileOpen(false)} />
      </div>

      {/* 主内容区 — 移动端自动留出汉堡按钮空间 */}
      <main className="flex-1 overflow-auto min-w-0 pt-12 md:pt-0">
        {children}
      </main>
    </div>
  );
}
