// 决策助理 API 代理

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

    let apiPath = `/api/advisor${subPath}`;
    if (queryString) {
      apiPath += `?${queryString}`;
    }

    let body: string | undefined;
    if (request.method !== "GET" && request.method !== "HEAD") {
      body = await request.text();
    }

    const isEvaluate = subPath === "/evaluate" && request.method === "POST";
    const flaskResponse = await proxyToFlask(apiPath, {
      method: request.method,
      body,
      ...(isEvaluate && { timeoutMs: 60_000 }),
    });

    const data = await flaskResponse.json();
    return NextResponse.json(data, { status: flaskResponse.status });
  } catch (error) {
    console.error("[Advisor API Proxy Error]:", error);
    const isTimeout =
      error instanceof DOMException && error.name === "AbortError";
    return NextResponse.json(
      {
        success: false,
        message: isTimeout
          ? "决策助理评估超时，请稍后重试"
          : "决策助理API代理失败",
      },
      { status: isTimeout ? 504 : 500 }
    );
  }
}

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ path?: string[] }> }
) {
  return handleRequest(request, context);
}

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ path?: string[] }> }
) {
  return handleRequest(request, context);
}
