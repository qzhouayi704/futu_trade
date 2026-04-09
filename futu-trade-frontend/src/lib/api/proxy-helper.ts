// API 代理层通用工具函数
// 连接到后端 API（FastAPI 或 Flask）

// 使用 127.0.0.1 而非 localhost，避免 Windows 上 IPv6 DNS 解析延迟
const FLASK_API_URL = process.env.FLASK_API_URL || "http://127.0.0.1:5001";

// 默认超时 30 秒（解决 undici UND_ERR_HEADERS_TIMEOUT 问题）
const DEFAULT_TIMEOUT_MS = 30_000;

export async function proxyToFlask(
  path: string,
  options?: RequestInit & { timeoutMs?: number }
): Promise<Response> {
  const url = `${FLASK_API_URL}${path}`;
  const timeoutMs = options?.timeoutMs ?? DEFAULT_TIMEOUT_MS;

  console.log(`[Proxy] ${options?.method || "GET"} ${path}`);

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const { timeoutMs: _, ...fetchOptions } = options ?? {};
    const response = await fetch(url, {
      ...fetchOptions,
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...options?.headers,
      },
    });

    return response;
  } catch (error) {
    console.error(`[Proxy Error] ${path}:`, error);
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

export async function handleProxyRequest(
  request: Request,
  apiPath: string
): Promise<Response> {
  try {
    // 获取查询参数
    const { searchParams } = new URL(request.url);
    const queryString = searchParams.toString();
    const fullPath = queryString ? `${apiPath}?${queryString}` : apiPath;

    // 获取请求体
    let body: string | undefined;
    if (request.method !== "GET" && request.method !== "HEAD") {
      body = await request.text();
    }

    // 转发请求到后端 API
    const flaskResponse = await proxyToFlask(fullPath, {
      method: request.method,
      body,
      headers: {
        "Content-Type": "application/json",
      },
    });

    // 获取响应数据
    const data = await flaskResponse.json();

    // 返回 Next.js Response
    return new Response(JSON.stringify(data), {
      status: flaskResponse.status,
      headers: {
        "Content-Type": "application/json",
      },
    });
  } catch (error) {
    console.error("[Proxy Handler Error]:", error);
    return new Response(
      JSON.stringify({
        success: false,
        message: "代理请求失败",
      }),
      {
        status: 500,
        headers: {
          "Content-Type": "application/json",
        },
      }
    );
  }
}
