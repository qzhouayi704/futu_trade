// 系统状态 API 代理

import { NextRequest, NextResponse } from "next/server";
import { proxyToFlask } from "@/lib/api/proxy-helper";

export async function GET(request: NextRequest) {
  try {
    const flaskResponse = await proxyToFlask("/api/status", {
      method: "GET",
    });

    const data = await flaskResponse.json();

    return NextResponse.json(data, {
      status: flaskResponse.status,
    });
  } catch (error) {
    console.error("[Status API Proxy Error]:", error);
    return NextResponse.json(
      { success: false, message: "状态API代理失败" },
      { status: 500 }
    );
  }
}
