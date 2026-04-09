// 增强热度分析 API 代理

import { NextRequest, NextResponse } from "next/server";
import { proxyToFlask } from "@/lib/api/proxy-helper";

async function handleRequest(
  request: NextRequest,
  context: { params: Promise<{ path?: string[] }> }
) {
  try {
    const params = await context.params;
    const subPath = params.path ? `/${params.path.join("/")}` : "";
    const { searchParams } = new URL(request.url);
    const queryString = searchParams.toString();

    let apiPath = `/api/enhanced-heat${subPath}`;
    if (queryString) {
      apiPath += `?${queryString}`;
    }

    const flaskResponse = await proxyToFlask(apiPath, {
      method: request.method,
    });

    const data = await flaskResponse.json();
    return NextResponse.json(data, { status: flaskResponse.status });
  } catch (error) {
    console.error("[Enhanced Heat API Proxy Error]:", error);
    return NextResponse.json(
      { success: false, message: "增强热度API代理失败" },
      { status: 500 }
    );
  }
}

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ path?: string[] }> }
) {
  return handleRequest(request, context);
}
