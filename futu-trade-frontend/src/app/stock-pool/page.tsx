// 重定向到系统管理的股票池Tab
"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function StockPoolRedirect() {
  const router = useRouter();
  useEffect(() => { router.replace("/settings?tab=pool"); }, [router]);
  return null;
}
