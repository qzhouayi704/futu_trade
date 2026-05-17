// 重定向到交易驾驶舱的交易条件Tab
"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function ConditionsRedirect() {
  const router = useRouter();
  useEffect(() => { router.replace("/trading?tab=conditions"); }, [router]);
  return null;
}
