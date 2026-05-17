-- 添加流动性字段到 stocks 表
-- 执行时间：2026-05-05

-- 添加流动性评分字段
ALTER TABLE stocks ADD COLUMN liquidity_score REAL DEFAULT 50.0;

-- 添加流动性等级字段
ALTER TABLE stocks ADD COLUMN liquidity_level VARCHAR(10) DEFAULT 'B';

-- 添加流动性评分更新时间字段
ALTER TABLE stocks ADD COLUMN liquidity_updated_at TIMESTAMP;

-- 创建索引以提升查询性能
CREATE INDEX IF NOT EXISTS idx_stocks_liquidity_score ON stocks(liquidity_score);
CREATE INDEX IF NOT EXISTS idx_stocks_liquidity_level ON stocks(liquidity_level);
