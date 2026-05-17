// 重定向到个股深度的价格位置Tab
"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function PriceAnalysisRedirect() {
  const router = useRouter();
  useEffect(() => { router.replace("/stock-detail?tab=price"); }, [router]);
  return null;
}
