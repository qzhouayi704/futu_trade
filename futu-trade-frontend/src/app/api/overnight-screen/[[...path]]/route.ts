// 盘后优选 API 代理

import { NextRequest } from "next/server";
import { handleProxyRequest } from "@/lib/api/proxy-helper";

async function handleRequest(
  request: NextRequest,
  context: { params: Promise<{ path?: string[] }> }
) {
  const params = await context.params;
  const subPath = params.path ? `/${params.path.join("/")}` : "";
  return handleProxyRequest(request, `/api/overnight-screen${subPath}`);
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
