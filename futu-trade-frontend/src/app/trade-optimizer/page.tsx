// 重定向到交易驾驶舱的风控管控Tab
"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function OptimizerRedirect() {
  const router = useRouter();
  useEffect(() => { router.replace("/trading?tab=optimizer"); }, [router]);
  return null;
}
