// 重定向到个股深度的综合分析Tab
"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function EnhancedHeatRedirect() {
  const router = useRouter();
  useEffect(() => { router.replace("/stock-detail?tab=analysis"); }, [router]);
  return null;
}
