#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基础表定义 - 股票、板块、K线
"""


class BaseTables:
    """基础数据表定义"""

    # 板块表
    # is_target: 是否为目标板块（用户选择关注的板块）
    # is_enabled: 是否启用（控制板块是否参与实时监控，默认TRUE）
    PLATES_TABLE = '''
        CREATE TABLE IF NOT EXISTS plates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plate_code VARCHAR(50) UNIQUE NOT NULL,
            plate_name VARCHAR(200) NOT NULL,
            market VARCHAR(10) NOT NULL,
            category VARCHAR(50),
            stock_count INTEGER DEFAULT 0,
            is_target BOOLEAN DEFAULT FALSE,
            is_enabled BOOLEAN DEFAULT TRUE,
            priority INTEGER DEFAULT 0,
            match_score INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    '''

    # 股票表 - 移除 plate_id，使用多对多关联
    STOCKS_TABLE = '''
        CREATE TABLE IF NOT EXISTS stocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code VARCHAR(20) UNIQUE NOT NULL,
            name VARCHAR(100),
            market VARCHAR(10) NOT NULL,
            is_manual BOOLEAN DEFAULT FALSE,
            stock_priority INTEGER DEFAULT 0,
            heat_score REAL DEFAULT 0,
            avg_turnover_rate REAL DEFAULT 0,
            avg_volume REAL DEFAULT 0,
            active_days INTEGER DEFAULT 0,
            heat_update_time TIMESTAMP,
            is_low_activity BOOLEAN DEFAULT FALSE,
            low_activity_checked_at TIMESTAMP,
            activity_score REAL DEFAULT 0,
            last_activity_check TIMESTAMP,
            low_activity_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    '''

    # 股票-板块关联表（多对多）
    STOCK_PLATES_TABLE = '''
        CREATE TABLE IF NOT EXISTS stock_plates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_id INTEGER NOT NULL,
            plate_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (stock_id) REFERENCES stocks(id) ON DELETE CASCADE,
            FOREIGN KEY (plate_id) REFERENCES plates(id) ON DELETE CASCADE,
            UNIQUE(stock_id, plate_id)
        )
    '''

    # K线数据表（日线）
    KLINE_DATA_TABLE = '''
        CREATE TABLE IF NOT EXISTS kline_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code VARCHAR(20) NOT NULL,
            time_key VARCHAR(20) NOT NULL,
            open_price DECIMAL(10,3),
            close_price DECIMAL(10,3),
            high_price DECIMAL(10,3),
            low_price DECIMAL(10,3),
            volume BIGINT,
            turnover DECIMAL(15,2),
            pe_ratio DECIMAL(8,2),
            turnover_rate DECIMAL(6,3),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(stock_code, time_key)
        )
    '''

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
