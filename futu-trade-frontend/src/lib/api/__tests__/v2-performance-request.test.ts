import axios, { AxiosError, type AxiosAdapter, type InternalAxiosRequestConfig } from "axios";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "../client";
import { v2Api } from "../v2";

const originalAdapter = apiClient.defaults.adapter;

beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.spyOn(console, "warn").mockImplementation(() => {});
});
afterEach(() => {
  apiClient.defaults.adapter = originalAdapter;
  vi.restoreAllMocks();
});

describe("bounded performance requests", () => {
  it("bounds paper ledger requests and does not multiply a timeout", async () => {
    const controller = new AbortController();
    const adapter = vi.fn<AxiosAdapter>(async (config) => {
      expect(config.timeout).toBe(10_000);
      expect(config.signal).toBe(controller.signal);
      throw new AxiosError("timeout", "ECONNABORTED", config);
    });
    apiClient.defaults.adapter = adapter;
    await expect(v2Api.paperLedger(controller.signal)).rejects.toMatchObject({ message: "timeout" });
    expect(adapter).toHaveBeenCalledTimes(1);
  });
  it("uses a 20-second timeout and forwards query cancellation", async () => {
    const controller = new AbortController();
    let received: InternalAxiosRequestConfig | undefined;
    apiClient.defaults.adapter = async (config) => {
      received = config;
      return { config, status: 200, statusText: "OK", headers: {}, data: { success: true, data: { count: 1 } } };
    };
    expect(await v2Api.alertPerformance("2026-09-07", "candidates", controller.signal)).toEqual({ count: 1 });
    expect(received?.timeout).toBe(20_000);
    expect(received?.signal).toBe(controller.signal);
  });

  it("does not multiply a timed-out performance request with Axios retries", async () => {
    const adapter = vi.fn<AxiosAdapter>(async (config) => {
      throw new AxiosError("timeout", "ECONNABORTED", config);
    });
    apiClient.defaults.adapter = adapter;
    await expect(v2Api.alertPerformance("2026-09-07", "candidates")).rejects.toMatchObject({ message: "timeout" });
    expect(adapter).toHaveBeenCalledTimes(1);
  });

  it("cancels before dispatch without treating it as a retryable failure", async () => {
    const adapter = vi.fn<AxiosAdapter>();
    apiClient.defaults.adapter = adapter;
    const controller = new AbortController();
    controller.abort();
    try {
      await v2Api.alertPerformance("2026-09-07", "candidates", controller.signal);
      throw new Error("request should have been canceled");
    } catch (error) {
      expect(axios.isCancel(error)).toBe(true);
    }
    expect(adapter).not.toHaveBeenCalled();
  });
});
