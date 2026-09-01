import { NextRequest, NextResponse } from "next/server";
import { proxyToFlask } from "@/lib/api/proxy-helper";

async function handleRequest(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  try {
    const { path } = await context.params;
    const query = new URL(request.url).searchParams.toString();
    const apiPath = `/api/v2/${path.join("/")}${query ? `?${query}` : ""}`;
    const response = await proxyToFlask(apiPath, { method: "GET" });
    return NextResponse.json(await response.json(), { status: response.status });
  } catch (error) {
    console.error("[V2 API Proxy Error]", error);
    return NextResponse.json(
      { success: false, message: "V2 API 代理失败" },
      { status: 500 },
    );
  }
}

export const GET = handleRequest;
