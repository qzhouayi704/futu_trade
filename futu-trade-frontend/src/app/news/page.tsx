"use client";

import { useState, useEffect, useCallback } from "react";
import { Card, Button, Loading } from "@/components/common";
import { newsApi } from "@/lib/api/news";
import type {
  News,
  HotStockFromNews,
  HotPlateFromNews,
  InvestmentSuggestion,
} from "@/types/news";

// 情感标签组件
function SentimentBadge({
  sentiment,
}: {
  sentiment?: "positive" | "negative" | "neutral";
}) {
  const config = {
    positive: { text: "利好", className: "bg-green-100 text-green-800" },
    negative: { text: "利空", className: "bg-red-100 text-red-800" },
    neutral: { text: "中性", className: "bg-gray-100 text-gray-800" },
  };
  const { text, className } = config[sentiment || "neutral"];
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${className}`}>
      {text}
    </span>
  );
}

// 新闻卡片组件
function NewsCard({ news }: { news: News }) {
  return (
    <div className="p-4 border-b border-gray-100 hover:bg-gray-50 transition-colors">
      <div className="flex items-start gap-3">
        <SentimentBadge sentiment={news.sentiment} />
        <div className="flex-1 min-w-0">
          <a
            href={news.news_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-gray-900 font-medium hover:text-blue-600 line-clamp-2"
          >
            {news.is_pinned && (
              <span className="text-orange-500 mr-1">[置顶]</span>
            )}
            {news.title}
          </a>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-gray-500">
            <span>{news.source}</span>
            {news.publish_time && (
              <>
                <span>·</span>
                <span>{news.publish_time}</span>
              </>
            )}
            {news.related_stocks && news.related_stocks.length > 0 && (
              <>
                <span>·</span>
                <span className="text-blue-600">
                  相关股票:{" "}
                  {news.related_stocks
                    .map((s) => s.stock_name || s.stock_code)
                    .join(", ")}
                </span>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// 投资建议卡片
function SuggestionsCard({
  suggestions,
  loading,
}: {
  suggestions: InvestmentSuggestion | null;
  loading: boolean;
}) {
  if (loading) return <Loading />;
  if (!suggestions) return <div className="text-gray-500">暂无数据</div>;

  return (
    <div className="space-y-4">
      {/* 看涨 */}
      <div>
        <h4 className="text-sm font-medium text-green-700 mb-2 flex items-center gap-1">
          <span className="w-2 h-2 bg-green-500 rounded-full"></span>
          看涨建议
        </h4>
        {suggestions.bullish.length > 0 ? (
          <div className="space-y-2">
            {suggestions.bullish.map((stock) => (
              <div
                key={stock.stock_code}
                className="p-2 bg-green-50 rounded text-sm"
              >
                <div className="font-medium text-green-800">
                  {stock.stock_name || stock.stock_code}
                </div>
                <div className="text-green-600 text-xs mt-1">{stock.reason}</div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-gray-400 text-sm">暂无看涨建议</div>
        )}
      </div>

      {/* 看跌 */}
      <div>
        <h4 className="text-sm font-medium text-red-700 mb-2 flex items-center gap-1">
          <span className="w-2 h-2 bg-red-500 rounded-full"></span>
          看跌提醒
        </h4>
        {suggestions.bearish.length > 0 ? (
          <div className="space-y-2">
            {suggestions.bearish.map((stock) => (
              <div
                key={stock.stock_code}
                className="p-2 bg-red-50 rounded text-sm"
              >
                <div className="font-medium text-red-800">
                  {stock.stock_name || stock.stock_code}
                </div>
                <div className="text-red-600 text-xs mt-1">{stock.reason}</div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-gray-400 text-sm">暂无看跌提醒</div>
        )}
      </div>
    </div>
  );
}

// 热门股票卡片
function HotStocksCard({
  stocks,
  loading,
}: {
  stocks: HotStockFromNews[];
  loading: boolean;
}) {
  if (loading) return <Loading />;

  return (
    <div className="space-y-2">
      {stocks.length > 0 ? (
        stocks.map((stock, index) => (
          <div
            key={`${stock.stock_code}-${index}`}
            className="flex items-center justify-between p-2 bg-gray-50 rounded"
          >
            <div className="flex items-center gap-2">
              <span className="text-gray-400 text-sm w-5">{index + 1}</span>
              <span className="font-medium">
                {stock.stock_name || stock.stock_code}
              </span>
            </div>
            <div className="flex items-center gap-2 text-sm">
              <span className="text-gray-500">{stock.mention_count}次</span>
              <span className={
                stock.positive_count > stock.negative_count
                  ? "text-green-600"
                  : stock.negative_count > stock.positive_count
                  ? "text-red-600"
                  : "text-gray-500"
              }>
                {stock.positive_count > stock.negative_count
                  ? "利好"
                  : stock.negative_count > stock.positive_count
                  ? "利空"
                  : "中性"}
              </span>
            </div>
          </div>
        ))
      ) : (
        <div className="text-gray-400 text-sm text-center py-4">暂无数据</div>
      )}
    </div>
  );
}

// 热门板块卡片
function HotPlatesCard({
  plates,
  loading,
}: {
  plates: HotPlateFromNews[];
  loading: boolean;
}) {
  if (loading) return <Loading />;

  return (
    <div className="space-y-2">
      {plates.length > 0 ? (
        plates.map((plate, index) => (
          <div
            key={`${plate.plate_code}-${index}`}
            className="flex items-center justify-between p-2 bg-gray-50 rounded"
          >
            <div className="flex items-center gap-2">
              <span className="text-gray-400 text-sm w-5">{index + 1}</span>
              <span className="font-medium">{plate.plate_name}</span>
            </div>
            <span className="text-gray-500 text-sm">
              {plate.mention_count}次提及
            </span>
          </div>
        ))
      ) : (
        <div className="text-gray-400 text-sm text-center py-4">暂无数据</div>
      )}
    </div>
  );
}

export default function NewsPage() {
  const [news, setNews] = useState<News[]>([]);
  const [hotStocks, setHotStocks] = useState<HotStockFromNews[]>([]);
  const [hotPlates, setHotPlates] = useState<HotPlateFromNews[]>([]);
  const [suggestions, setSuggestions] = useState<InvestmentSuggestion | null>(
    null
  );
  const [loading, setLoading] = useState(true);
  const [crawling, setCrawling] = useState(false);
  const [timeRange, setTimeRange] = useState<number>(24); // 默认24小时

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [newsRes, stocksRes, platesRes, suggestionsRes] = await Promise.all(
        [
          newsApi.getLatestNews(30, timeRange),
          newsApi.getHotStocksFromNews(timeRange || 24, 10),
          newsApi.getHotPlatesFromNews(timeRange || 24, 10),
          newsApi.getInvestmentSuggestions(5, timeRange || 24),
        ]
      );

      if (newsRes.success) setNews(newsRes.data?.news || []);
      if (stocksRes.success) setHotStocks(stocksRes.data?.stocks || []);
      if (platesRes.success) setHotPlates(platesRes.data?.plates || []);
      if (suggestionsRes.success) setSuggestions(suggestionsRes.data || null);
    } catch (error) {
      console.error("加载数据失败:", error);
    } finally {
      setLoading(false);
    }
  }, [timeRange]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleCrawl = async (debug: boolean = false) => {
    setCrawling(true);
    try {
      const result = await newsApi.triggerCrawl(50, debug);
      if (result.success) {
        const newCount = result.data?.new_count || 0;
        const crawledCount = result.data?.crawled_count || 0;

        if (newCount === 0 && crawledCount > 0) {
          alert(`抓取完成，但所有新闻都已存在（共抓取 ${crawledCount} 条）`);
        } else {
          alert(`抓取完成！\n- 抓取: ${crawledCount} 条\n- 新增: ${newCount} 条`);
        }
        loadData();
      } else {
        // 显示详细的错误信息
        const errorMsg = result.message || "抓取失败";
        alert(`抓取失败\n\n原因：${errorMsg}\n\n建议：\n- 检查网络连接\n- 稍后重试\n- 如果问题持续，请联系管理员`);
      }
    } catch (error) {
      console.error("抓取失败:", error);
      alert(`抓取失败\n\n原因：无法连接到后端服务\n\n建议：\n- 确认后端服务正在运行（端口 5001）\n- 检查网络连接\n- 查看浏览器控制台获取详细错误`);
    } finally {
      setCrawling(false);
    }
  };

  return (
    <div className="p-6 space-y-6">
      {/* 页面标题 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <h1 className="text-2xl font-bold text-gray-900">热点新闻分析</h1>
          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-600">时间范围：</span>
            <select
              value={timeRange}
              onChange={(e) => setTimeRange(Number(e.target.value))}
              className="px-3 py-1 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value={24}>24小时</option>
              <option value={168}>7天</option>
              <option value={720}>30天</option>
              <option value={0}>全部</option>
            </select>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Button onClick={loadData} disabled={loading} variant="secondary">
            刷新数据
          </Button>
          <Button onClick={() => handleCrawl(false)} disabled={crawling}>
            {crawling ? "抓取中..." : "抓取新闻"}
          </Button>
          <Button onClick={() => handleCrawl(true)} disabled={crawling} variant="secondary">
            调试抓取
          </Button>
        </div>
      </div>

      {/* 顶部卡片区域 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card
          title="投资建议"
          subtitle={`基于近${timeRange === 24 ? '24小时' : timeRange === 168 ? '7天' : timeRange === 720 ? '30天' : '全部'}新闻分析`}
        >
          <SuggestionsCard suggestions={suggestions} loading={loading} />
        </Card>

        <Card title="热门股票" subtitle="新闻提及次数排行">
          <HotStocksCard stocks={hotStocks} loading={loading} />
        </Card>

        <Card title="热门板块" subtitle="新闻提及次数排行">
          <HotPlatesCard plates={hotPlates} loading={loading} />
        </Card>
      </div>

      {/* 新闻列表 */}
      <Card title="新闻列表" subtitle={`共 ${news.length} 条新闻`}>
        {loading ? (
          <Loading />
        ) : news.length > 0 ? (
          <div className="divide-y divide-gray-100">
            {news.map((item) => (
              <NewsCard key={item.id} news={item} />
            ))}
          </div>
        ) : (
          <div className="text-center py-12 text-gray-500">
            <p>该时间范围内暂无新闻数据</p>
            <p className="text-sm mt-2">尝试扩大时间范围或点击"抓取新闻"获取最新数据</p>
          </div>
        )}
      </Card>
    </div>
  );
}
