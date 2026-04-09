// 新闻 API

import apiClient from "./client";
import type { ApiResponse } from "@/types";
import type {
  News,
  HotStockFromNews,
  HotPlateFromNews,
  InvestmentSuggestion,
  NewsStatus,
  CrawlResult,
} from "@/types/news";

export const newsApi = {
  // 获取最新新闻
  getLatestNews: async (
    limit: number = 20,
    hours: number = 0,
    offset: number = 0
  ): Promise<ApiResponse<{ news: News[]; total: number; has_more: boolean }>> => {
    const params: Record<string, number> = { limit, offset };
    if (hours > 0) {
      params.hours = hours;
    }
    return apiClient.get("/news/latest", { params });
  },

  // 获取股票相关新闻
  getNewsByStock: async (
    stockCode: string,
    limit: number = 10
  ): Promise<ApiResponse<{ news: News[]; stock_code: string }>> => {
    return apiClient.get(`/news/stock/${stockCode}`, {
      params: { limit },
    });
  },

  // 按情感获取新闻
  getNewsBySentiment: async (
    sentiment: "positive" | "negative" | "neutral",
    limit: number = 20
  ): Promise<ApiResponse<{ news: News[]; sentiment: string }>> => {
    return apiClient.get(`/news/sentiment/${sentiment}`, {
      params: { limit },
    });
  },

  // 获取新闻热门股票
  getHotStocksFromNews: async (
    hours: number = 24,
    limit: number = 10
  ): Promise<ApiResponse<{ stocks: HotStockFromNews[]; hours: number }>> => {
    return apiClient.get("/news/hot-stocks", {
      params: { hours, limit },
    });
  },

  // 获取新闻热门板块
  getHotPlatesFromNews: async (
    hours: number = 24,
    limit: number = 10
  ): Promise<ApiResponse<{ plates: HotPlateFromNews[]; hours: number }>> => {
    return apiClient.get("/news/hot-plates", {
      params: { hours, limit },
    });
  },

  // 获取投资建议
  getInvestmentSuggestions: async (
    limit: number = 5,
    hours: number = 24
  ): Promise<ApiResponse<InvestmentSuggestion>> => {
    return apiClient.get("/news/suggestions", {
      params: { limit, hours },
    });
  },

  // 手动触发新闻抓取
  triggerCrawl: async (
    maxItems: number = 50,
    debug: boolean = false
  ): Promise<ApiResponse<CrawlResult>> => {
    return apiClient.post("/news/crawl", {
      max_items: maxItems,
      debug: debug,
    });
  },

  // 获取新闻服务状态
  getStatus: async (): Promise<ApiResponse<NewsStatus>> => {
    return apiClient.get("/news/status");
  },
};
