#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
业务表定义 - 交易、新闻、止盈、系统配置等
"""


class BusinessTables:
    """业务数据表定义"""

    # 5分钟K线数据表（用于日内交易回测）
    KLINE_5MIN_DATA_TABLE = '''
        CREATE TABLE IF NOT EXISTS kline_5min_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code VARCHAR(20) NOT NULL,
            time_key VARCHAR(30) NOT NULL,
            open_price DECIMAL(10,3),
            close_price DECIMAL(10,3),
            high_price DECIMAL(10,3),
            low_price DECIMAL(10,3),
            volume BIGINT,
            turnover DECIMAL(15,2),
            turnover_rate DECIMAL(6,3),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(stock_code, time_key)
        )
    '''

    # 交易信号表
    TRADE_SIGNALS_TABLE = '''
        CREATE TABLE IF NOT EXISTS trade_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_id INTEGER NOT NULL,
            signal_type VARCHAR(10) NOT NULL,
            signal_price DECIMAL(10,3) NOT NULL,
            target_price DECIMAL(10,3),
            stop_loss_price DECIMAL(10,3),
            condition_text TEXT,
            strategy_id VARCHAR(50),
            strategy_name VARCHAR(100),
            is_executed BOOLEAN DEFAULT FALSE,
            executed_time TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (stock_id) REFERENCES stocks(id)
        )
    '''

    # 系统配置表
    # 决策流水线表：记录信号从产生到最终动作的完整过程。
    SIGNAL_PIPELINE_TABLE = '''
        CREATE TABLE IF NOT EXISTS signal_pipeline (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            stock_code TEXT NOT NULL,
            stock_name TEXT,
            source TEXT,
            direction TEXT,
            strength REAL,
            resonance_result TEXT,
            guard_result TEXT,
            final_action TEXT,
            final_reason TEXT,
            raw_detail TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    '''

    SIGNAL_PIPELINE_INDEXES = [
        'CREATE INDEX IF NOT EXISTS idx_signal_pipeline_date ON signal_pipeline(trade_date)',
        'CREATE INDEX IF NOT EXISTS idx_signal_pipeline_code ON signal_pipeline(stock_code, trade_date)',
    ]

    SYSTEM_CONFIG_TABLE = '''
        CREATE TABLE IF NOT EXISTS system_config (
            key VARCHAR(50) PRIMARY KEY,
            value TEXT,
            description TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    '''

    # 订阅快照表 - 用于 OpenD 重连后按优先级恢复订阅
    SUBSCRIPTION_SNAPSHOT_TABLE = '''
        CREATE TABLE IF NOT EXISTS subscription_snapshot (
            type TEXT PRIMARY KEY,
            codes TEXT NOT NULL,
            updated_at INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    '''

    # 板块匹配日志表
    PLATE_MATCH_LOG_TABLE = '''
        CREATE TABLE IF NOT EXISTS plate_match_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plate_code VARCHAR(50) NOT NULL,
            plate_name VARCHAR(200) NOT NULL,
            matched BOOLEAN DEFAULT FALSE,
            category VARCHAR(50),
            match_score INTEGER DEFAULT 0,
            matched_keyword VARCHAR(100),
            match_type VARCHAR(20),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    '''

    # 交易记录表 - 用于K线图显示买卖点
    TRADING_RECORDS_TABLE = '''
        CREATE TABLE IF NOT EXISTS trading_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code VARCHAR(20) NOT NULL,
            trade_type VARCHAR(10) NOT NULL,
            trade_price DECIMAL(10,3) NOT NULL,
            trade_quantity INTEGER DEFAULT 0,
            trade_time TIMESTAMP NOT NULL,
            order_id VARCHAR(50),
            note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    '''

    # 每日活跃股票表
    DAILY_ACTIVE_STOCKS_TABLE = '''
        CREATE TABLE IF NOT EXISTS daily_active_stocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            check_date TEXT NOT NULL,
            stock_code TEXT NOT NULL,
            market TEXT NOT NULL,
            is_active INTEGER NOT NULL,
            activity_score REAL DEFAULT 0,
            turnover_rate REAL DEFAULT 0,
            turnover_amount REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(check_date, stock_code)
        )
    '''

    # 新闻表
    NEWS_TABLE = '''
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            news_id VARCHAR(100) UNIQUE NOT NULL,
            title VARCHAR(500) NOT NULL,
            summary TEXT,
            source VARCHAR(100),
            publish_time TIMESTAMP,
            news_url VARCHAR(500),
            image_url VARCHAR(500),
            sentiment VARCHAR(20),
            sentiment_score REAL DEFAULT 0,
            is_pinned BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    '''

    # 新闻-股票关联表
    NEWS_STOCKS_TABLE = '''
        CREATE TABLE IF NOT EXISTS news_stocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            news_id INTEGER NOT NULL,
            stock_code VARCHAR(20) NOT NULL,
            stock_name VARCHAR(100),
            impact_type VARCHAR(20),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (news_id) REFERENCES news(id) ON DELETE CASCADE,
            UNIQUE(news_id, stock_code)
        )
    '''

    # 新闻-板块关联表
    NEWS_PLATES_TABLE = '''
        CREATE TABLE IF NOT EXISTS news_plates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            news_id INTEGER NOT NULL,
            plate_code VARCHAR(50) NOT NULL,
            plate_name VARCHAR(200),
            impact_type VARCHAR(20),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (news_id) REFERENCES news(id) ON DELETE CASCADE,
            UNIQUE(news_id, plate_code)
        )
    '''

    # 分仓止盈任务表
    TAKE_PROFIT_TASKS_TABLE = '''
        CREATE TABLE IF NOT EXISTS take_profit_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code TEXT NOT NULL,
            stock_name TEXT,
            take_profit_pct REAL NOT NULL,
            status TEXT DEFAULT 'ACTIVE',
            total_lots INTEGER DEFAULT 0,
            sold_lots INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    '''

    # 止盈执行记录表
    TAKE_PROFIT_EXECUTIONS_TABLE = '''
        CREATE TABLE IF NOT EXISTS take_profit_executions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            stock_code TEXT NOT NULL,
            lot_buy_price REAL NOT NULL,
            lot_quantity INTEGER NOT NULL,
            trigger_price REAL NOT NULL,
            sell_price REAL,
            profit_amount REAL,
            status TEXT DEFAULT 'PENDING',
            triggered_at TIMESTAMP,
            executed_at TIMESTAMP,
            error_msg TEXT,
            deal_id TEXT,
            order_id TEXT,
            FOREIGN KEY (task_id) REFERENCES take_profit_tasks(id)
        )
    '''

    # 预设离场计划表（盘前为持仓定"开盘若X则卖"，开盘检查读取，专治开盘干等信号）
    EXIT_PLANS_TABLE = '''
        CREATE TABLE IF NOT EXISTS exit_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_id INTEGER NOT NULL,
            stock_code TEXT NOT NULL,
            planned_action TEXT NOT NULL,
            trigger_type TEXT NOT NULL,
            trigger_value REAL,
            note TEXT,
            valid_for_date TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (stock_id) REFERENCES stocks(id)
        )
    '''

    # 持仓做T腿表（高抛低吸的两腿状态机：卖一档→回落买回；先告警后半自动，专治"看到了却干等/手慢"）
    T_TRADE_LEGS_TABLE = '''
        CREATE TABLE IF NOT EXISTS t_trade_legs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_id INTEGER NOT NULL,
            stock_code TEXT NOT NULL,
            stock_name TEXT,
            trade_date TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'IDLE',
            mode TEXT NOT NULL DEFAULT 'alert',
            sold_qty INTEGER DEFAULT 0,
            sold_price REAL,
            sold_time TIMESTAMP,
            sell_order_id TEXT,
            sell_reason TEXT,
            target_buyback_price REAL,
            bought_price REAL,
            bought_time TIMESTAMP,
            buy_order_id TEXT,
            buy_reason TEXT,
            peak_after_sell REAL,
            trough_after_sell REAL,
            realized_pnl REAL,
            original_qty INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (stock_id) REFERENCES stocks(id)
        )
    '''

    # 资金流向缓存表
    CAPITAL_FLOW_CACHE_TABLE = '''
        CREATE TABLE IF NOT EXISTS capital_flow_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code VARCHAR(20) NOT NULL,
            timestamp TIMESTAMP NOT NULL,
            main_net_inflow DECIMAL(15,2),
            super_large_inflow DECIMAL(15,2),
            large_inflow DECIMAL(15,2),
            medium_inflow DECIMAL(15,2),
            small_inflow DECIMAL(15,2),
            super_large_outflow DECIMAL(15,2),
            large_outflow DECIMAL(15,2),
            medium_outflow DECIMAL(15,2),
            small_outflow DECIMAL(15,2),
            net_inflow_ratio DECIMAL(5,4),
            big_order_buy_ratio DECIMAL(5,4),
            capital_score DECIMAL(5,2),
            inflow_change DECIMAL(15,2) DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(stock_code, timestamp)
        )
    '''

    # 资金流向日线缓存表（每只股票每天一条，真实多日历史）
    CAPITAL_FLOW_DAILY_TABLE = '''
        CREATE TABLE IF NOT EXISTS capital_flow_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code VARCHAR(20) NOT NULL,
            date DATE NOT NULL,
            net_inflow DECIMAL(15,2),
            net_inflow_ratio DECIMAL(5,4),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(stock_code, date)
        )
    '''

    # 大单追踪表
    BIG_ORDER_TRACKING_TABLE = '''
        CREATE TABLE IF NOT EXISTS big_order_tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code VARCHAR(20) NOT NULL,
            timestamp TIMESTAMP NOT NULL,
            big_buy_count INTEGER DEFAULT 0,
            big_sell_count INTEGER DEFAULT 0,
            big_buy_amount DECIMAL(15,2),
            big_sell_amount DECIMAL(15,2),
            buy_sell_ratio DECIMAL(5,2),
            order_strength DECIMAL(5,2),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(stock_code, timestamp)
        )
    '''

    # 每日大单累计表（按天汇总超大单/大单买卖金额）
    DAILY_ORDER_ACCUMULATOR_TABLE = '''
        CREATE TABLE IF NOT EXISTS daily_order_accumulator (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code VARCHAR(20) NOT NULL,
            trade_date TEXT NOT NULL,
            super_large_buy_amt DECIMAL(15,2) DEFAULT 0,
            super_large_sell_amt DECIMAL(15,2) DEFAULT 0,
            large_buy_amt DECIMAL(15,2) DEFAULT 0,
            large_sell_amt DECIMAL(15,2) DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(stock_code, trade_date)
        )
    '''

    # 逐笔主力资金表（推送驱动累加器落库的快照流；与富途 capital_flow 双跑对照）
    # 时间序列(每次 flush 一行)便于看日内演化 + 与富途口径对照回放
    TICK_CAPITAL_FLOW_TABLE = '''
        CREATE TABLE IF NOT EXISTS tick_capital_flow (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code VARCHAR(20) NOT NULL,
            trade_date TEXT NOT NULL,
            timestamp TIMESTAMP NOT NULL,
            cum_main_net DECIMAL(18,2),
            window_main_net DECIMAL(18,2),
            super_large_buy DECIMAL(18,2),
            super_large_sell DECIMAL(18,2),
            large_buy DECIMAL(18,2),
            large_sell DECIMAL(18,2),
            big_order_buy_ratio DECIMAL(5,4),
            cum_peak DECIMAL(18,2),
            cum_trough DECIMAL(18,2),
            big_buy_count INTEGER DEFAULT 0,
            big_sell_count INTEGER DEFAULT 0,
            last_seq INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(stock_code, timestamp)
        )
    '''

    # 自动交易任务表
    AUTO_TRADE_TASKS_TABLE = '''
        CREATE TABLE IF NOT EXISTS auto_trade_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            zone TEXT,
            buy_dip_pct REAL NOT NULL,
            sell_rise_pct REAL NOT NULL,
            stop_loss_pct REAL NOT NULL,
            prev_close REAL NOT NULL,
            buy_target REAL NOT NULL,
            sell_target REAL NOT NULL,
            stop_price REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'waiting_buy',
            buy_price_actual REAL DEFAULT 0,
            sell_price_actual REAL DEFAULT 0,
            buy_date TEXT,
            message TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    '''

    # 信号效果追踪表
    SIGNAL_PERFORMANCE_TABLE = '''
        CREATE TABLE IF NOT EXISTS signal_performance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id INTEGER NOT NULL,
            stock_code TEXT NOT NULL,
            signal_type TEXT NOT NULL,
            signal_price REAL NOT NULL,
            strategy_id TEXT,
            day1_max_rise REAL,
            day1_max_drop REAL,
            day3_max_rise REAL,
            day3_max_drop REAL,
            day5_max_rise REAL,
            day5_max_drop REAL,
            day1_close_ret REAL,
            day3_close_ret REAL,
            day5_close_ret REAL,
            tracking_status TEXT DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (signal_id) REFERENCES trade_signals(id)
        )
    '''

    # 决策助理评估记录表
    ADVISOR_EVALUATIONS_TABLE = '''
        CREATE TABLE IF NOT EXISTS advisor_evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            advice_type VARCHAR(20) NOT NULL,
            urgency INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            sell_stock_code VARCHAR(20),
            sell_stock_name VARCHAR(100),
            sell_price DECIMAL(10,3),
            buy_stock_code VARCHAR(20),
            buy_stock_name VARCHAR(100),
            buy_price DECIMAL(10,3),
            quantity INTEGER,
            sell_ratio REAL,
            health_score REAL,
            health_level VARCHAR(20),
            ai_analysis TEXT,
            is_dismissed BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    '''

    # ========== Scalping 引擎数据表 ==========

    # Scalping 交易信号表
    SCALPING_SIGNALS_TABLE = '''
        CREATE TABLE IF NOT EXISTS scalping_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code VARCHAR(20) NOT NULL,
            signal_type VARCHAR(20) NOT NULL,
            trigger_price DECIMAL(10,3) NOT NULL,
            support_price DECIMAL(10,3),
            conditions TEXT,
            trade_date TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    '''

    # Scalping Delta 历史记录表
    SCALPING_DELTA_HISTORY_TABLE = '''
        CREATE TABLE IF NOT EXISTS scalping_delta_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code VARCHAR(20) NOT NULL,
            delta REAL NOT NULL,
            volume INTEGER NOT NULL,
            period_seconds INTEGER NOT NULL,
            trade_date TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    '''

    # Scalping POC 成交量分布快照表（每股每天一条）
    SCALPING_POC_SNAPSHOT_TABLE = '''
        CREATE TABLE IF NOT EXISTS scalping_poc_snapshot (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code VARCHAR(20) NOT NULL,
            poc_price DECIMAL(10,3) NOT NULL,
            volume_profile TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(stock_code, trade_date)
        )
    '''

    # Scalping 阻力/支撑线事件表
    SCALPING_PRICE_LEVELS_TABLE = '''
        CREATE TABLE IF NOT EXISTS scalping_price_levels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code VARCHAR(20) NOT NULL,
            price DECIMAL(10,3) NOT NULL,
            volume INTEGER NOT NULL,
            side VARCHAR(15) NOT NULL,
            action VARCHAR(10) NOT NULL,
            trade_date TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    '''

    # 逐笔成交明细表（用于回溯分析和诊断）
    # 去重唯一键 = 业务键 (stock_code, trade_date, trade_time, price, volume, direction)。
    #   富途逐笔无稳定唯一 ID：sequence 跨请求每次重新编号（实测同一笔成交两次拉取序号全不同），
    #   接收时刻 timestamp 也随拉取时间变——两者都不能做去重轴。唯一稳定的是富途回报的"真实成交
    #   时间 trade_time + 价/量/方向"业务组合（与 routers/.../ticker_flow.py 的去重口径一致）。
    #   - trade_time: 富途真实成交时间（毫秒），去重键核心；旧行为 NULL（NULL 互不相等不误撞）
    #   - sequence  : 富途逐笔序号，仅留存不做键（跨请求会变）
    #   - timestamp : 本地接收时刻，留存不做键
    # 取舍：同股同毫秒同价同量同向的两笔不同成交会被当一笔（富途无唯一 ID 的固有局限）。
    TICKER_DATA_TABLE = '''
        CREATE TABLE IF NOT EXISTS ticker_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code VARCHAR(20) NOT NULL,
            price DECIMAL(10,3) NOT NULL,
            volume INTEGER NOT NULL,
            turnover DECIMAL(15,2),
            direction VARCHAR(10) NOT NULL,
            timestamp BIGINT NOT NULL,
            trade_date TEXT NOT NULL,
            sequence BIGINT,
            trade_time TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(stock_code, trade_date, trade_time, price, volume, direction)
        )
    '''

    # 逐笔数据表索引
    TICKER_DATA_INDEXES = [
        'CREATE INDEX IF NOT EXISTS idx_ticker_stock_date ON ticker_data(stock_code, trade_date)',
        'CREATE INDEX IF NOT EXISTS idx_ticker_timestamp ON ticker_data(timestamp)',
    ]

    # Scalping 交易事件表（诱多/诱空、假突破、动能点火等）
    SCALPING_EVENTS_TABLE = '''
        CREATE TABLE IF NOT EXISTS scalping_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code VARCHAR(20) NOT NULL,
            event_type VARCHAR(30) NOT NULL,
            event_data TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    '''

    # 盘后优选结果持久化表
    OVERNIGHT_SCREEN_RESULTS_TABLE = '''
        CREATE TABLE IF NOT EXISTS overnight_screen_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            screen_date TEXT NOT NULL,
            candidates_json TEXT NOT NULL,
            total_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(screen_date)
        )
    '''

    SCALPING_EVENTS_INDEXES = [
        'CREATE INDEX IF NOT EXISTS idx_scalping_events_stock_date ON scalping_events(stock_code, trade_date)',
    ]

    # 盘中狙击信号持久化表
    SNIPER_SIGNALS_TABLE = '''
        CREATE TABLE IF NOT EXISTS sniper_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date TEXT NOT NULL,
            time TEXT NOT NULL,
            stock_code VARCHAR(20) NOT NULL,
            stock_name VARCHAR(100),
            signal_type VARCHAR(30) NOT NULL,
            is_red BOOLEAN NOT NULL,
            price DECIMAL(10,3),
            detail TEXT,
            action TEXT,
            severity VARCHAR(10) DEFAULT 'high',
            strength INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    '''

    SNIPER_SIGNALS_INDEXES = [
        'CREATE INDEX IF NOT EXISTS idx_sniper_signals_date ON sniper_signals(trade_date)',
        'CREATE INDEX IF NOT EXISTS idx_sniper_signals_code ON sniper_signals(stock_code, trade_date)',
    ]

    # 历史基准统计表（用于动态阈值自适应）
    MARKET_BASELINES_TABLE = '''
        CREATE TABLE IF NOT EXISTS market_baselines (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code  VARCHAR(20) NOT NULL,
            metric_key  VARCHAR(50) NOT NULL,
            window_days INTEGER NOT NULL,
            mean        REAL,
            stddev      REAL,
            p25         REAL,
            p50         REAL,
            p75         REAL,
            p90         REAL,
            sample_count INTEGER DEFAULT 0,
            computed_at  TIMESTAMP NOT NULL,
            UNIQUE(stock_code, metric_key, window_days)
        )
    '''

    # 分时数据持久化表（保存获取到的RT_DATA）
    RT_DATA_TABLE = '''
        CREATE TABLE IF NOT EXISTS rt_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code VARCHAR(20) NOT NULL,
            time VARCHAR(30) NOT NULL,
            cur_price DECIMAL(10,3),
            avg_price DECIMAL(10,3),
            volume BIGINT,
            turnover DECIMAL(15,2),
            trade_date TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(stock_code, time)
        )
    '''

    # 分时数据表索引
    RT_DATA_INDEXES = [
        'CREATE INDEX IF NOT EXISTS idx_rt_data_stock_date ON rt_data(stock_code, trade_date)',
        'CREATE INDEX IF NOT EXISTS idx_rt_data_time ON rt_data(time)',
    ]

    # CCASS 经纪商持仓数据（T+1，来自 HKEX）
    CCASS_HOLDINGS_TABLE = '''
        CREATE TABLE IF NOT EXISTS ccass_holdings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code VARCHAR(20) NOT NULL,
            holding_date TEXT NOT NULL,
            participant_id VARCHAR(20),
            participant_name TEXT NOT NULL,
            shareholding BIGINT DEFAULT 0,
            percent DECIMAL(10,4) DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(stock_code, holding_date, participant_id)
        )
    '''

    CCASS_HOLDINGS_INDEXES = [
        'CREATE INDEX IF NOT EXISTS idx_ccass_stock_date ON ccass_holdings(stock_code, holding_date)',
    ]

    # ========== 交易系统 V2 影子内核 ==========

    V2_DECISION_EVENTS_TABLE = '''
        CREATE TABLE IF NOT EXISTS v2_decision_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL UNIQUE,
            event_type TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            strategy_version TEXT NOT NULL,
            stock_code TEXT NOT NULL,
            exchange_time TEXT NOT NULL,
            received_time TEXT NOT NULL,
            sequence INTEGER,
            correlation_id TEXT NOT NULL,
            source TEXT NOT NULL,
            old_state TEXT,
            new_state TEXT,
            reason_code TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    '''

    V2_STRATEGY_STATES_TABLE = '''
        CREATE TABLE IF NOT EXISTS v2_strategy_states (
            strategy_version TEXT NOT NULL,
            stock_code TEXT NOT NULL,
            status TEXT NOT NULL,
            version INTEGER NOT NULL,
            last_event_id TEXT NOT NULL,
            confirmed_price REAL,
            peak_price REAL,
            last_sequence INTEGER,
            metadata_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (strategy_version, stock_code),
            FOREIGN KEY (last_event_id) REFERENCES v2_decision_events(event_id)
        )
    '''

    V2_POSITION_STATES_TABLE = '''
        CREATE TABLE IF NOT EXISTS v2_position_states (
            strategy_version TEXT NOT NULL,
            stock_code TEXT NOT NULL,
            status TEXT NOT NULL,
            version INTEGER NOT NULL,
            last_event_id TEXT NOT NULL,
            opened_at TEXT NOT NULL,
            cost_price REAL NOT NULL,
            peak_price REAL NOT NULL,
            trough_price REAL NOT NULL,
            mfe_pct REAL NOT NULL,
            mae_pct REAL NOT NULL,
            last_high_at TEXT NOT NULL,
            stalled_since TEXT,
            profit_ready_since TEXT,
            flow_peak REAL NOT NULL,
            metadata_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (strategy_version, stock_code),
            FOREIGN KEY (last_event_id) REFERENCES v2_decision_events(event_id)
        )
    '''

    V2_TRADE_INTENTS_TABLE = '''
        CREATE TABLE IF NOT EXISTS v2_trade_intents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            intent_id TEXT NOT NULL UNIQUE,
            source_event_id TEXT NOT NULL,
            intent_type TEXT NOT NULL,
            mode TEXT NOT NULL,
            sell_leg_json TEXT,
            buy_leg_json TEXT,
            risk_result TEXT,
            risk_reason_json TEXT,
            broker_order_ids_json TEXT,
            status TEXT NOT NULL DEFAULT 'PENDING',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(source_event_id, intent_type),
            FOREIGN KEY (source_event_id) REFERENCES v2_decision_events(event_id)
        )
    '''

    V2_NOTIFICATION_LOG_TABLE = '''
        CREATE TABLE IF NOT EXISTS v2_notification_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            decision_event_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            channel TEXT NOT NULL,
            status TEXT NOT NULL,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            expires_at TEXT,
            delivered_at TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(idempotency_key, channel),
            FOREIGN KEY (decision_event_id) REFERENCES v2_decision_events(event_id)
        )
    '''

    V2_OUTCOMES_TABLE = '''
        CREATE TABLE IF NOT EXISTS v2_outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            decision_event_id TEXT NOT NULL UNIQUE,
            stock_code TEXT NOT NULL,
            strategy_version TEXT NOT NULL,
            signal_time TEXT NOT NULL,
            signal_price REAL NOT NULL,
            mfe_pct REAL,
            mae_pct REAL,
            close_return_pct REAL,
            next_day_return_pct REAL,
            reached_1_5 INTEGER,
            reached_3 INTEGER,
            reached_5 INTEGER,
            time_to_1_5_seconds INTEGER,
            time_to_3_seconds INTEGER,
            time_to_5_seconds INTEGER,
            time_to_peak_seconds INTEGER,
            hold_control_return_pct REAL,
            rotation_return_pct REAL,
            evaluated_at TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (decision_event_id) REFERENCES v2_decision_events(event_id)
        )
    '''

    V2_INDEXES = [
        'CREATE INDEX IF NOT EXISTS idx_v2_events_stock_time ON v2_decision_events(stock_code, exchange_time)',
        'CREATE INDEX IF NOT EXISTS idx_v2_events_strategy_type_time ON v2_decision_events(strategy_version, event_type, exchange_time)',
        'CREATE INDEX IF NOT EXISTS idx_v2_events_type_time_stock ON v2_decision_events(event_type, exchange_time, stock_code)',
        'CREATE INDEX IF NOT EXISTS idx_v2_events_correlation ON v2_decision_events(correlation_id)',
        'CREATE INDEX IF NOT EXISTS idx_v2_states_status ON v2_strategy_states(status, updated_at)',
        'CREATE INDEX IF NOT EXISTS idx_v2_position_states_status ON v2_position_states(status, updated_at)',
        'CREATE INDEX IF NOT EXISTS idx_v2_intents_status ON v2_trade_intents(status, updated_at)',
        'CREATE INDEX IF NOT EXISTS idx_v2_notifications_status ON v2_notification_log(status, updated_at)',
        'CREATE INDEX IF NOT EXISTS idx_v2_outcomes_strategy_time ON v2_outcomes(strategy_version, signal_time)',
    ]
