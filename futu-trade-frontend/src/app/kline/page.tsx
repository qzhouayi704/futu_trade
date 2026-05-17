// 重定向到个股深度的K线Tab
"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function KlineRedirect() {
  const router = useRouter();
  useEffect(() => { router.replace("/stock-detail?tab=kline"); }, [router]);
  return null;
}
