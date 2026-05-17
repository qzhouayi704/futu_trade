// 重定向到系统管理的未订阅Tab
"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function UnsubRedirect() {
  const router = useRouter();
  useEffect(() => { router.replace("/settings?tab=unsub"); }, [router]);
  return null;
}
