// 重定向到交易驾驶舱的交易规则Tab
"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function FlowSignalsRedirect() {
  const router = useRouter();
  useEffect(() => { router.replace("/trading?tab=rules"); }, [router]);
  return null;
}
