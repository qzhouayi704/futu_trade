// 侧边栏导航组件 — Apple × 金融科技风格

"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { useTheme } from "next-themes";

interface NavItem {
  name: string;
  path: string;
  icon: React.ReactNode;
}

interface NavGroup {
  label: string;
  emoji: string;
  items: NavItem[];
}

// ── 图标工厂 ──────────────────────────────────────
const Icon = ({ d }: { d: string }) => (
  <svg className="w-[18px] h-[18px] flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.6} d={d} />
  </svg>
);

// ── 5大模块 ──────────────────────────────────────

const navGroups: NavGroup[] = [
  {
    label: "盘面总览",
    emoji: "📊",
    items: [
      {
        name: "系统概览",
        path: "/",
        icon: <Icon d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />,
      },
      {
        name: "板块热度",
        path: "/plates",
        icon: <Icon d="M17.657 18.657A8 8 0 016.343 7.343S7 9 9 10c0-2 .5-5 2.986-7C14 5 16.09 5.777 17.656 7.343A7.975 7.975 0 0120 13a7.975 7.975 0 01-2.343 5.657z" />,
      },
      {
        name: "热点新闻",
        path: "/news",
        icon: <Icon d="M19 20H5a2 2 0 01-2-2V6a2 2 0 012-2h10a2 2 0 012 2v1m2 13a2 2 0 01-2-2V7m2 13a2 2 0 002-2V9a2 2 0 00-2-2h-2m-4-3H9M7 16h6M7 8h6v4H7V8z" />,
      },
    ],
  },
  {
    label: "选股工作台",
    emoji: "🎯",
    items: [
      {
        name: "选股工作台",
        path: "/stock-picker",
        icon: <Icon d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />,
      },
    ],
  },
  {
    label: "交易执行",
    emoji: "📈",
    items: [
      {
        name: "交易决策中心",
        path: "/pre-check",
        icon: <Icon d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />,
      },
      {
        name: "交易驾驶舱",
        path: "/trading",
        icon: <Icon d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />,
      },
      {
        name: "持仓监控",
        path: "/positions",
        icon: <Icon d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />,
      },
    ],
  },
  {
    label: "个股深度",
    emoji: "🔍",
    items: [
      {
        name: "个股深度分析",
        path: "/stock-detail",
        icon: <Icon d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />,
      },
    ],
  },
  {
    label: "系统管理",
    emoji: "⚙️",
    items: [
      {
        name: "策略管理",
        path: "/strategies",
        icon: <Icon d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />,
      },
      {
        name: "系统管理",
        path: "/settings",
        icon: <Icon d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />,
      },
    ],
  },
];

// 收集所有路径（用于 active 匹配）
const allItems = navGroups.flatMap((g) => g.items);

interface SidebarProps {
  onNavigate?: () => void;
}

export function Sidebar({ onNavigate }: SidebarProps) {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const { theme, setTheme } = useTheme();

  const toggleGroup = (label: string) => {
    setCollapsed((prev) => ({ ...prev, [label]: !prev[label] }));
  };

  const isGroupActive = (group: NavGroup) =>
    group.items.some((item) => {
      if (item.path === "/") return pathname === "/";
      return pathname === item.path || pathname.startsWith(item.path + "/");
    });

  return (
    <aside className="w-[260px] md:w-[220px] min-h-screen flex flex-col border-r border-sidebar-border bg-sidebar">
      {/* 移动端关闭按钮 */}
      <button
        onClick={onNavigate}
        className="absolute top-3 right-3 z-10 md:hidden flex items-center justify-center w-8 h-8 rounded-lg hover:bg-sidebar-accent transition-colors"
        aria-label="关闭菜单"
      >
        <svg className="w-5 h-5 text-sidebar-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
      {/* Logo */}
      <div className="px-4 py-4 border-b border-sidebar-border">
        <Link href="/" className="flex items-center space-x-2.5 group">
          <div className="w-8 h-8 rounded-[10px] bg-gradient-to-br from-primary to-primary/80 flex items-center justify-center shadow-sm group-hover:shadow-md transition-shadow">
            <svg className="w-4 h-4 text-primary-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
            </svg>
          </div>
          <div>
            <span className="text-[15px] font-semibold tracking-tight text-sidebar-foreground">富途量化</span>
          </div>
        </Link>
      </div>

      {/* Navigation */}
      <nav className="flex-1 py-2 px-2.5 overflow-y-auto">
        {navGroups.map((group) => {
          const active = isGroupActive(group);
          const isCollapsed = collapsed[group.label] ?? false;

          return (
            <div key={group.label} className="mb-1">
              <button
                onClick={() => toggleGroup(group.label)}
                className={`w-full flex items-center justify-between px-2 py-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] transition-colors rounded-md ${
                  active ? "text-primary" : "text-muted-foreground hover:text-sidebar-foreground"
                }`}
              >
                <span className="flex items-center gap-1.5">
                  <span className="text-[10px]">{group.emoji}</span>
                  <span>{group.label}</span>
                </span>
                <svg
                  className={`w-3 h-3 opacity-40 transition-transform duration-200 ${isCollapsed ? "-rotate-90" : ""}`}
                  fill="none" viewBox="0 0 24 24" stroke="currentColor"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M19 9l-7 7-7-7" />
                </svg>
              </button>

              {!isCollapsed && (
                <ul className="space-y-0.5 mt-0.5">
                  {group.items.map((item) => {
                    const hasMoreSpecificMatch = allItems.some(
                      (other) =>
                        other.path !== item.path &&
                        other.path.startsWith(item.path + "/") &&
                        (pathname === other.path || pathname.startsWith(other.path + "/"))
                    );
                    const isActive =
                      item.path === "/"
                        ? pathname === "/"
                        : !hasMoreSpecificMatch &&
                          (pathname === item.path || pathname.startsWith(item.path + "/"));

                    return (
                      <li key={item.path}>
                        <Link
                          href={item.path}
                          onClick={onNavigate}
                          className={`flex items-center gap-2.5 px-2.5 py-[9px] md:py-[7px] rounded-lg text-[14px] md:text-[13px] transition-all duration-200 ${
                            isActive
                              ? "bg-primary text-primary-foreground font-semibold shadow-sm shadow-primary/20"
                              : "text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground font-medium"
                          }`}
                        >
                          <span className={isActive ? "opacity-100" : "opacity-60"}>{item.icon}</span>
                          <span>{item.name}</span>
                        </Link>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="px-3 py-3 border-t border-sidebar-border">
        <button
          onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          className="w-full flex items-center gap-2 px-2.5 py-2 rounded-lg text-[13px] font-medium text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground transition-all"
        >
          <span className="text-base">{theme === "dark" ? "☀️" : "🌙"}</span>
          <span>{theme === "dark" ? "浅色模式" : "深色模式"}</span>
        </button>
      </div>
    </aside>
  );
}
