"use client";

import { useTheme } from "next-themes";
import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  if (!mounted) return <div className="w-9 h-9" />;

  return (
    <button
      onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
      className="w-9 h-9 rounded-lg flex items-center justify-center
                 border border-gray-200 dark:border-gray-700
                 bg-white dark:bg-gray-800
                 hover:bg-gray-100 dark:hover:bg-gray-700
                 transition-colors"
      title={theme === "dark" ? "切换亮色模式" : "切换暗色模式"}
    >
      {theme === "dark" ? (
        <Sun className="w-4 h-4 text-amber-400" />
      ) : (
        <Moon className="w-4 h-4 text-gray-500" />
      )}
    </button>
  );
}
