// 价格位置分析 API 代理

import { NextRequest, NextResponse } from "next/server";
import { proxyToFlask } from "@/lib/api/proxy-helper";

async function handleRequest(request: NextRequest, context: { params: Promise<{ path?: string[] }> }) {
  try {
    const params = await context.params;
    const subPath = params.path ? `/${params.path.join("/")}` : "";
    const { searchParams } = new URL(request.url);
    const queryString = searchParams.toString();

    let apiPath = `/api/analysis${subPath}`;
    if (queryString) {
      apiPath += `?${queryString}`;
    }

    let body: string | undefined;
    if (request.method !== "GET" && request.method !== "HEAD") {
      body = await request.text();
    }

    const flaskResponse = await proxyToFlask(apiPath, {
      method: request.method,
      body,
    });

    const data = await flaskResponse.json();

    return NextResponse.json(data, {
      status: flaskResponse.status,
    });
  } catch (error) {
    console.error("[Analysis API Proxy Error]:", error);
    return NextResponse.json(
      { success: false, message: "分析API代理失败" },
      { status: 500 }
    );
  }
}

export async function GET(request: NextRequest, context: { params: Promise<{ path?: string[] }> }) {
  return handleRequest(request, context);
}

export async function POST(request: NextRequest, context: { params: Promise<{ path?: string[] }> }) {
  return handleRequest(request, context);
}
