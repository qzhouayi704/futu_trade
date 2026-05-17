// 快速扫描 API 代理

import { NextRequest, NextResponse } from "next/server";
import { proxyToFlask } from "@/lib/api/proxy-helper";

async function handleRequest(request: NextRequest, context: { params: Promise<{ path?: string[] }> }) {
  try {
    const params = await context.params;
    const subPath = params.path ? `/${params.path.join("/")}` : "";

    const body = await request.json();

    const flaskResponse = await proxyToFlask(`/api/quick-scan${subPath}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    const data = await flaskResponse.json();

    return NextResponse.json(data, {
      status: flaskResponse.status,
    });
  } catch (error) {
    console.error("[Quick Scan API Proxy Error]:", error);
    return NextResponse.json(
      { success: false, message: "快速扫描API代理失败" },
      { status: 500 }
    );
  }
}

export async function POST(request: NextRequest, context: { params: Promise<{ path?: string[] }> }) {
  return handleRequest(request, context);
}
