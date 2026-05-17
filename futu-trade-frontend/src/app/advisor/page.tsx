// 重定向到系统管理的决策助理Tab
"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function AdvisorRedirect() {
  const router = useRouter();
  useEffect(() => { router.replace("/settings?tab=advisor"); }, [router]);
  return null;
}
