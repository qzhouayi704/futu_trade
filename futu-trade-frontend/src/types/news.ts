// 新闻类型定义

export interface News {
  id: number;
  news_id: string;
  title: string;
  summary?: string;
  source?: string;
  publish_time?: string;
  news_url?: string;
  image_url?: string;
  sentiment?: "positive" | "negative" | "neutral";
  sentiment_score?: number;
  is_pinned?: boolean;
  created_at?: string;
  related_stocks?: NewsStock[];
  related_plates?: NewsPlate[];
}

export interface NewsStock {
  stock_code: string;
  stock_name?: string;
  impact_type?: "positive" | "negative" | "neutral";
}

export interface NewsPlate {
  plate_code: string;
  plate_name?: string;
  impact_type?: "positive" | "negative" | "neutral";
}

export interface HotStockFromNews {
  stock_code: string;
  stock_name?: string;
  mention_count: number;
  positive_count: number;
  negative_count: number;
  sentiment_score: number;
  reason?: string;
}

export interface HotPlateFromNews {
  plate_code: string;
  plate_name?: string;
  mention_count: number;
  positive_count: number;
  negative_count: number;
}

export interface InvestmentSuggestion {
  bullish: HotStockFromNews[];
  bearish: HotStockFromNews[];
  generated_at: string;
}

export interface NewsStatus {
  is_crawling: boolean;
  last_crawl_time?: string;
  crawler_available: boolean;
}

export interface CrawlResult {
  success: boolean;
  crawled_count: number;
  analyzed_count: number;
  new_count: number;
  errors: string[];
  message?: string;
}
