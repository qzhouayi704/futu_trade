// 股票 API 代理（支持所有子路径）

import { NextRequest, NextResponse } from "next/server";
import { proxyToFlask } from "@/lib/api/proxy-helper";

async function handleRequest(request: NextRequest, context: { params: Promise<{ path?: string[] }> }) {
  try {
    // 构建完整路径
    const params = await context.params;
    const subPath = params.path ? `/${params.path.join("/")}` : "";
    const { searchParams } = new URL(request.url);
    const queryString = searchParams.toString();

    let apiPath = `/api/stocks${subPath}`;
    if (queryString) {
      apiPath += `?${queryString}`;
    }

    // 获取请求体
    let body: string | undefined;
    if (request.method !== "GET" && request.method !== "HEAD") {
      body = await request.text();
    }

    // 转发到 Flask
    const flaskResponse = await proxyToFlask(apiPath, {
      method: request.method,
      body,
    });

    const data = await flaskResponse.json();

    return NextResponse.json(data, {
      status: flaskResponse.status,
    });
  } catch (error) {
    console.error("[Stocks API Proxy Error]:", error);
    return NextResponse.json(
      { success: false, message: "股票API代理失败" },
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

export async function PUT(request: NextRequest, context: { params: Promise<{ path?: string[] }> }) {
  return handleRequest(request, context);
}

export async function DELETE(request: NextRequest, context: { params: Promise<{ path?: string[] }> }) {
  return handleRequest(request, context);
}
