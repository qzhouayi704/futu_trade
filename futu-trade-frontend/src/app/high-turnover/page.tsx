// 重定向到选股工作台的活跃排行Tab
"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function HighTurnoverRedirect() {
  const router = useRouter();
  useEffect(() => { router.replace("/stock-picker?tab=active"); }, [router]);
  return null;
}
