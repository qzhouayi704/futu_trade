-- 资金流向缓存表
CREATE TABLE IF NOT EXISTS capital_flow_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code VARCHAR(20) NOT NULL,
    timestamp TIMESTAMP NOT NULL,

    -- 资金流向数据
    main_net_inflow DECIMAL(15,2),      -- 主力净流入
    super_large_inflow DECIMAL(15,2),   -- 超大单流入
    large_inflow DECIMAL(15,2),         -- 大单流入
    medium_inflow DECIMAL(15,2),        -- 中单流入
    small_inflow DECIMAL(15,2),         -- 小单流入

    super_large_outflow DECIMAL(15,2),  -- 超大单流出
    large_outflow DECIMAL(15,2),        -- 大单流出
    medium_outflow DECIMAL(15,2),       -- 中单流出
    small_outflow DECIMAL(15,2),        -- 小单流出

    -- 计算指标
    net_inflow_ratio DECIMAL(5,4),      -- 净流入占比
    big_order_buy_ratio DECIMAL(5,4),   -- 大单买入占比
    capital_score DECIMAL(5,2),         -- 资金评分

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(stock_code, timestamp)
);

CREATE INDEX IF NOT EXISTS idx_capital_flow_code ON capital_flow_cache(stock_code);
CREATE INDEX IF NOT EXISTS idx_capital_flow_time ON capital_flow_cache(timestamp);
CREATE INDEX IF NOT EXISTS idx_capital_flow_score ON capital_flow_cache(capital_score DESC);

-- 大单追踪表
CREATE TABLE IF NOT EXISTS big_order_tracking (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code VARCHAR(20) NOT NULL,
    timestamp TIMESTAMP NOT NULL,

    -- 大单数据
    big_buy_count INTEGER DEFAULT 0,    -- 大单买入笔数
    big_sell_count INTEGER DEFAULT 0,   -- 大单卖出笔数
    big_buy_amount DECIMAL(15,2),       -- 大单买入金额
    big_sell_amount DECIMAL(15,2),      -- 大单卖出金额

    -- 计算指标
    buy_sell_ratio DECIMAL(5,2),        -- 买卖比
    order_strength DECIMAL(5,2),        -- 大单强度

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(stock_code, timestamp)
);

CREATE INDEX IF NOT EXISTS idx_big_order_code ON big_order_tracking(stock_code);
CREATE INDEX IF NOT EXISTS idx_big_order_time ON big_order_tracking(timestamp);
CREATE INDEX IF NOT EXISTS idx_big_order_strength ON big_order_tracking(order_strength DESC);
