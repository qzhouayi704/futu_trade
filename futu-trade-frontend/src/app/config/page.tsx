// 重定向到系统管理的配置Tab
"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function ConfigRedirect() {
  const router = useRouter();
  useEffect(() => { router.replace("/settings?tab=config"); }, [router]);
  return null;
}
