// 新闻 API 代理路由

import { NextRequest, NextResponse } from "next/server";
import { handleProxyRequest } from "@/lib/api/proxy-helper";

// 设置API路由的最大执行时间为120秒（支持新闻抓取等耗时操作）
export const maxDuration = 120;

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path?: string[] }> }
) {
  const { path } = await params;
  const apiPath = `/api/news${path ? "/" + path.join("/") : ""}`;
  return handleProxyRequest(request, apiPath);
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path?: string[] }> }
) {
  const { path } = await params;
  const apiPath = `/api/news${path ? "/" + path.join("/") : ""}`;
  return handleProxyRequest(request, apiPath);
}
