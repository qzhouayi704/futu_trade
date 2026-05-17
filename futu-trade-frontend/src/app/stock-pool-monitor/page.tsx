// 已废弃 → 重定向到选股工作台（MarketScan 已包含全部功能）
"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function StockPoolMonitorRedirect() {
  const router = useRouter();
  useEffect(() => { router.replace("/stock-picker?tab=scan"); }, [router]);
  return null;
}
