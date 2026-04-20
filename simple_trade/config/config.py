#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置管理模块

提供配置类定义、加载、保存和验证功能。
配置分为以下几类：
- 连接配置：富途API连接参数
- 交易配置：自动交易开关和阈值
- 预警配置：5分钟价格变化预警
- 数据配置：股票池和K线数据限制
"""

import os
import json
import logging
from dataclasses import dataclass, asdict, field, fields
from typing import Dict, Any, List, Optional, Tuple


# ------------------------------------------------------------------
# 嵌套配置 dataclass（支持 .get() 兼容旧代码的 dict 访问方式）
# ------------------------------------------------------------------

class _ConfigMixin:
    """为配置 dataclass 提供 dict 兼容的 .get() 方法"""
    def get(self, key: str, default=None):
        return getattr(self, key, default)

    def __getitem__(self, key: str):
        return getattr(self, key)

    def __contains__(self, key: str):
        return hasattr(self, key)


@dataclass
class KlineRateLimitConfig(_ConfigMixin):
    """K线请求频率控制配置"""
    enabled: bool = True
    max_requests: int = 60
    time_window: int = 30
    request_delay: float = 1.0
    fast_mode_delay: float = 0.5
    batch_delay: float = 0.5


@dataclass
class KlineRetryConfig(_ConfigMixin):
    """K线请求重试配置"""
    enabled: bool = True
    max_retries: int = 3
    initial_backoff: float = 1.0
    max_backoff: float = 32.0
    backoff_multiplier: float = 2.0


@dataclass
class RealtimeActivityFilterConfig(_ConfigMixin):
    """实时活跃度筛选配置"""
    enabled: bool = True
    min_turnover_rate: float = 0.2
    min_turnover_amount: int = 5000000
    low_activity_recheck_days: int = 7


@dataclass
class RealtimeHotFilterConfig(_ConfigMixin):
    """实时热门股筛选配置"""
    enabled: bool = True
    min_volume: int = 100000
    turnover_rate_weight: float = 0.4
    turnover_weight: float = 0.6
    turnover_rate_max_threshold: float = 5.0
    turnover_max_threshold: int = 50000000


@dataclass
class GeminiConfig(_ConfigMixin):
    """Gemini AI 配置"""
    api_key: str = "AIzaSyAEYkoUaP2kYhhKY2BuoBHO704vWjh0DwI"
    model: str = "gemini-3-flash-preview"
    enabled: bool = True
    timeout: int = 30
    max_retries: int = 3


@dataclass
class GeminiAnalystConfig(_ConfigMixin):
    """Gemini 量化分析师配置"""
    enabled: bool = False
    min_urgency: int = 8
    price_surge_threshold: float = 2.0
    price_plunge_threshold: float = -2.0
    capital_anomaly_threshold: float = 0.5
    cooldown_seconds: int = 300
    max_triggers_per_cycle: int = 3
    cache_ttl: int = 300


@dataclass
class SubscriptionConfig(_ConfigMixin):
    """订阅配置"""
    max_quote_subscription: int = 300
    max_ticker_subscription: int = 100
    max_orderbook_subscription: int = 100
    scalping_max_stocks: int = 15
    enable_auto_replace: bool = True


@dataclass
class ScalpingProcessConfig(_ConfigMixin):
    """Scalping 多进程超时配置"""
    spawn_timeout: float = 60.0       # 子进程初始化超时（秒）
    start_timeout: float = 60.0       # start 命令超时（秒）
    stop_timeout: float = 5.0         # stop 命令超时（秒）
    snapshot_timeout: float = 5.0     # snapshot 命令超时（秒）
    heartbeat_interval: float = 30.0  # 子进程心跳间隔（秒）
    heartbeat_timeout: float = 60.0   # 心跳超时判定（秒）
    max_restarts: int = 3             # 最大自动重启次数


@dataclass
class LoggingConfig(_ConfigMixin):
    """日志配置"""
    console_level: str = "WARNING"
    file_level: str = "INFO"
    enable_quote_debug: bool = False
    enable_scalping_debug: bool = False
    quote_log_interval: int = 10


def _to_config_obj(cls, value):
    """将 dict 转换为对应的配置 dataclass 实例（兼容 JSON 加载）"""
    if isinstance(value, cls):
        return value
    if isinstance(value, dict):
        # 只传入 dataclass 中定义的字段，忽略多余的 key
        valid_keys = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in value.items() if k in valid_keys}
        return cls(**filtered)
    return cls()


@dataclass
class Config:
    """
    系统配置类
    
    使用 dataclass 自动生成 __init__ 和其他方法。
    所有字段都有默认值，可以从 JSON 文件部分加载。
    """
    
    # ==================== 连接配置 ====================
    futu_host: str = "127.0.0.1"           # 富途OpenD主机地址
    futu_port: int = 11111                  # 富途OpenD端口
    database_path: str = "simple_trade/data/trade.db"  # 数据库路径
    
    # ==================== 交易配置 ====================
    update_interval: int = 60               # 数据更新间隔(秒)
    auto_trade: bool = True                 # 自动交易开关
    price_change_threshold: float = 3.0     # 价格变化阈值(%)
    volume_surge_threshold: float = 2.0     # 成交量激增阈值(倍)
    
    # ==================== 预警配置 ====================
    alert_5min_rise_threshold: float = 2.0     # 5分钟内涨幅阈值(%)
    alert_5min_fall_threshold: float = 3.0     # 5分钟内跌幅阈值(%)
    alert_5min_amplitude_threshold: float = 5.0 # 5分钟内振幅阈值(%)
    price_history_duration: int = 300          # 价格历史保留时长(秒)
    alert_cooldown_seconds: int = 300          # 预警冷却期（秒）
    alert_percent_increment_threshold: float = 1.0  # 预警涨跌幅增量阈值（百分比）
    min_breakout_amplitude: float = 1.0            # 日内振幅最小阈值(%)，低于此值跳过价格突破预警

    # ==================== 监控配置 ====================
    max_stocks_monitor: int = 800           # 最大监控股票数
    max_subscription_stocks: int = 300      # 最大订阅股票数量
    monitor_stocks_limit_by_market: dict = field(default_factory=lambda: {
        "HK": 25,
        "US": 50
    })                                      # 按市场的订阅数量限制
    kline_priority_enabled: bool = True     # K线优先订阅开关
    log_kline_detail: bool = True           # 是否记录K线详细日志
    
    # ==================== 优先级配置 ====================
    priority_thresholds: dict = field(default_factory=lambda: {
        "high": 80,
        "medium": 50,
        "low": 10
    })
    
    # ==================== 数据限制配置 ====================
    max_recent_signals: int = 50            # 最近交易信号数量
    max_active_stocks: int = 800            # 活跃股票池大小
    max_subscribed_stocks: int = 800        # 订阅股票数量
    max_plate_stocks: int = 800             # 板块股票数量
    max_quality_plates: int = 20            # 优质板块数量
    max_target_plates: int = 50             # 目标板块数量
    kline_days: int = 30                    # K线数据天数
    max_kline_records: int = 200            # K线记录数量
    stocks_per_plate: int = 50              # 每个板块股票数量
    max_stocks_for_kline_update: int = 300  # K线更新股票数量
    max_stocks_for_trading: int = 1000      # 交易用股票数量
    
    # ==================== K线初始化配置 ====================
    kline_init_days: int = 180              # K线初始化获取天数（半年）
    kline_batch_size: int = 10              # K线批量获取每批股票数量
    kline_request_delay: float = 0.3        # K线请求间隔（秒）
    auto_init_kline: bool = True            # 板块初始化后自动初始化K线
    kline_init_max_stocks: int = 500        # K线初始化最大股票数量

    # ==================== K线请求频率控制配置 ====================
    kline_rate_limit: KlineRateLimitConfig = field(default_factory=KlineRateLimitConfig)

    # ==================== K线请求重试配置 ====================
    kline_retry: KlineRetryConfig = field(default_factory=KlineRetryConfig)

    # ==================== 实时活跃度筛选配置 ====================
    realtime_activity_filter: RealtimeActivityFilterConfig = field(default_factory=RealtimeActivityFilterConfig)

    # ==================== 实时热门股筛选配置 ====================
    realtime_hot_filter: RealtimeHotFilterConfig = field(default_factory=RealtimeHotFilterConfig)

    # ==================== Gemini AI 配置 ====================
    gemini: GeminiConfig = field(default_factory=GeminiConfig)

    # ==================== Gemini 量化分析师配置 ====================
    gemini_analyst: GeminiAnalystConfig = field(default_factory=GeminiAnalystConfig)

    # ==================== 策略配置 ====================
    strategies: dict = field(default_factory=lambda: {
        "active_strategy": "trend_reversal",
        "available": {}
    })

    # ==================== 日志配置 ====================
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    # ==================== 订阅配置 ====================
    subscription_config: SubscriptionConfig = field(default_factory=SubscriptionConfig)

    # ==================== Scalping 多进程配置 ====================
    scalping_process: ScalpingProcessConfig = field(default_factory=ScalpingProcessConfig)

    def __post_init__(self):
        """JSON 加载时自动将 dict 转换为嵌套 dataclass"""
        _conversions = {
            'kline_rate_limit': KlineRateLimitConfig,
            'kline_retry': KlineRetryConfig,
            'realtime_activity_filter': RealtimeActivityFilterConfig,
            'realtime_hot_filter': RealtimeHotFilterConfig,
            'gemini': GeminiConfig,
            'gemini_analyst': GeminiAnalystConfig,
            'logging': LoggingConfig,
            'subscription_config': SubscriptionConfig,
            'scalping_process': ScalpingProcessConfig,
        }
        for attr, cls in _conversions.items():
            val = getattr(self, attr)
            if isinstance(val, dict):
                object.__setattr__(self, attr, _to_config_obj(cls, val))


class ConfigValidator:
    """配置验证器"""
    
    # 验证规则定义
    VALIDATION_RULES: Dict[str, Dict[str, Any]] = {
        # 连接配置
        'futu_host': {'type': str, 'required': True},
        'futu_port': {'type': int, 'min': 1, 'max': 65535, 'required': True},
        'database_path': {'type': str, 'required': True},
        
        # 交易配置
        'update_interval': {'type': int, 'min': 1, 'max': 3600},
        'auto_trade': {'type': bool},
        'price_change_threshold': {'type': (int, float), 'min': 0, 'max': 100},
        'volume_surge_threshold': {'type': (int, float), 'min': 0, 'max': 100},
        
        # 预警配置
        'alert_5min_rise_threshold': {'type': (int, float), 'min': 0, 'max': 100},
        'alert_5min_fall_threshold': {'type': (int, float), 'min': 0, 'max': 100},
        'alert_5min_amplitude_threshold': {'type': (int, float), 'min': 0, 'max': 100},
        'price_history_duration': {'type': int, 'min': 60, 'max': 3600},
        'alert_cooldown_seconds': {'type': int, 'min': 0, 'max': 3600},
        'alert_percent_increment_threshold': {'type': (int, float), 'min': 0, 'max': 10},
        
        # 监控配置
        'max_stocks_monitor': {'type': int, 'min': 1, 'max': 5000},
        'max_subscription_stocks': {'type': int, 'min': 1, 'max': 1000},
        'kline_priority_enabled': {'type': bool},
        'log_kline_detail': {'type': bool},
        
        # 数据限制配置
        'max_recent_signals': {'type': int, 'min': 1, 'max': 1000},
        'max_active_stocks': {'type': int, 'min': 1, 'max': 5000},
        'max_subscribed_stocks': {'type': int, 'min': 1, 'max': 5000},
        'max_plate_stocks': {'type': int, 'min': 1, 'max': 5000},
        'max_quality_plates': {'type': int, 'min': 1, 'max': 100},
        'max_target_plates': {'type': int, 'min': 1, 'max': 200},
        'kline_days': {'type': int, 'min': 1, 'max': 365},
        'max_kline_records': {'type': int, 'min': 1, 'max': 1000},
        'stocks_per_plate': {'type': int, 'min': 1, 'max': 500},
        'max_stocks_for_kline_update': {'type': int, 'min': 1, 'max': 1000},
        'max_stocks_for_trading': {'type': int, 'min': 1, 'max': 5000},
    }
    
    @classmethod
    def validate(cls, data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        验证配置数据
        
        Args:
            data: 配置字典
            
        Returns:
            (是否有效, 错误信息列表)
        """
        errors = []
        
        for field_name, rules in cls.VALIDATION_RULES.items():
            # 检查必填字段
            if rules.get('required') and field_name not in data:
                errors.append(f"缺少必填配置项: {field_name}")
                continue
            
            # 如果字段存在，进行验证
            if field_name in data:
                value = data[field_name]
                
                # 类型检查
                expected_type = rules.get('type')
                if expected_type and not isinstance(value, expected_type):
                    type_name = expected_type.__name__ if hasattr(expected_type, '__name__') else str(expected_type)
                    errors.append(f"{field_name}: 类型错误，期望 {type_name}，实际 {type(value).__name__}")
                    continue
                
                # 数值范围检查
                if isinstance(value, (int, float)):
                    min_val = rules.get('min')
                    max_val = rules.get('max')
                    if min_val is not None and value < min_val:
                        errors.append(f"{field_name}: 值 {value} 小于最小值 {min_val}")
                    if max_val is not None and value > max_val:
                        errors.append(f"{field_name}: 值 {value} 大于最大值 {max_val}")
        
        # 验证 priority_thresholds 结构
        if 'priority_thresholds' in data:
            pt = data['priority_thresholds']
            if not isinstance(pt, dict):
                errors.append("priority_thresholds: 必须是字典类型")
            else:
                for key in ['high', 'medium', 'low']:
                    if key not in pt:
                        errors.append(f"priority_thresholds: 缺少 {key} 字段")
                    elif not isinstance(pt[key], (int, float)):
                        errors.append(f"priority_thresholds.{key}: 必须是数值类型")
        
        return len(errors) == 0, errors
    
    @classmethod
    def validate_and_raise(cls, data: Dict[str, Any]) -> None:
        """
        验证配置数据，如果无效则抛出异常
        
        Args:
            data: 配置字典
            
        Raises:
            ValueError: 配置验证失败
        """
        is_valid, errors = cls.validate(data)
        if not is_valid:
            raise ValueError(f"配置验证失败:\n" + "\n".join(f"  - {e}" for e in errors))


class ConfigManager:
    """配置管理器"""
    
    # 默认配置文件路径
    DEFAULT_CONFIG_PATH = "simple_trade/config.json"
    
    @classmethod
    def load_config(cls, config_path: str = None) -> Config:
        """
        加载配置文件，支持环境变量覆盖

        环境变量命名规则：FUTU_ + 配置项大写
        例如：FUTU_HOST, FUTU_PORT, FUTU_DATABASE_PATH, FUTU_AUTO_TRADE

        Args:
            config_path: 配置文件路径，默认为 simple_trade/config.json

        Returns:
            Config 对象
        """
        if config_path is None:
            config_path = cls.DEFAULT_CONFIG_PATH

        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # 验证配置
                is_valid, errors = ConfigValidator.validate(data)
                if not is_valid:
                    logging.warning(f"配置验证警告:\n" + "\n".join(f"  - {e}" for e in errors))

                # 过滤掉 Config 类不认识的字段
                valid_fields = {f.name for f in fields(Config)}
                filtered_data = {k: v for k, v in data.items() if k in valid_fields}

                # 应用环境变量覆盖（仅覆盖关键配置）
                cls._apply_env_overrides(filtered_data)

                return Config(**filtered_data)
            except json.JSONDecodeError as e:
                logging.error(f"配置文件 JSON 解析失败: {e}")
            except Exception as e:
                logging.warning(f"配置文件加载失败，使用默认配置: {e}")

        # 创建默认配置文件
        config = Config()
        cls.save_config(config, config_path)
        return config

    @classmethod
    def _apply_env_overrides(cls, config_data: Dict[str, Any]) -> None:
        """
        应用环境变量覆盖（仅覆盖部署相关的关键配置）

        支持的环境变量：
        - FUTU_HOST: 富途OpenD主机地址
        - FUTU_PORT: 富途OpenD端口
        - FUTU_DATABASE_PATH: 数据库路径
        - FUTU_AUTO_TRADE: 自动交易开关
        - FUTU_UPDATE_INTERVAL: 数据更新间隔
        - FUTU_MAX_SUBSCRIPTION_STOCKS: 最大订阅股票数量

        Args:
            config_data: 配置字典（会被原地修改）
        """
        # 定义支持环境变量覆盖的配置项及其类型转换函数
        env_mappings = {
            'FUTU_HOST': ('futu_host', str),
            'FUTU_PORT': ('futu_port', int),
            'FUTU_DATABASE_PATH': ('database_path', str),
            'FUTU_AUTO_TRADE': ('auto_trade', lambda x: x.lower() in ('true', '1', 'yes')),
            'FUTU_UPDATE_INTERVAL': ('update_interval', int),
            'FUTU_MAX_SUBSCRIPTION_STOCKS': ('max_subscription_stocks', int),
        }

        for env_key, (config_key, converter) in env_mappings.items():
            env_value = os.environ.get(env_key)
            if env_value is not None:
                try:
                    config_data[config_key] = converter(env_value)
                    logging.info(f"配置项 {config_key} 已被环境变量 {env_key} 覆盖")
                except (ValueError, TypeError) as e:
                    logging.warning(f"环境变量 {env_key}={env_value} 转换失败: {e}")

        # Gemini 配置（从环境变量注入）
        cls._apply_gemini_env(config_data)

    @classmethod
    def _apply_gemini_env(cls, config_data: Dict[str, Any]) -> None:
        """
        从环境变量注入 Gemini 配置

        支持的环境变量：
        - GEMINI_API_KEY: API 密钥（必需）
        - GEMINI_MODEL: 模型名称（可选）
        - GEMINI_ENABLED: 是否启用（可选，有 API key 时默认启用）
        - GEMINI_TIMEOUT: 超时时间（可选）
        """
        gemini = config_data.get('gemini', {})

        api_key = os.environ.get('GEMINI_API_KEY')
        if api_key:
            gemini['api_key'] = api_key

        model = os.environ.get('GEMINI_MODEL')
        if model:
            gemini['model'] = model

        enabled = os.environ.get('GEMINI_ENABLED')
        if enabled is not None:
            gemini['enabled'] = enabled.lower() in ('true', '1', 'yes')
        elif api_key and 'enabled' not in gemini:
            # 有 API key 时默认启用
            gemini['enabled'] = True

        timeout = os.environ.get('GEMINI_TIMEOUT')
        if timeout:
            try:
                gemini['timeout'] = int(timeout)
            except ValueError:
                pass

        if gemini.get('api_key'):
            config_data['gemini'] = gemini
            logging.info("Gemini 配置已从环境变量加载")

    @classmethod
    def save_config(cls, config: Config, config_path: str = None) -> bool:
        """
        保存配置文件
        
        Args:
            config: Config 对象
            config_path: 配置文件路径
            
        Returns:
            是否保存成功
        """
        if config_path is None:
            config_path = cls.DEFAULT_CONFIG_PATH
            
        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            
            # 使用 asdict 自动转换
            config_dict = asdict(config)
            
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config_dict, f, ensure_ascii=False, indent=2)
            
            logging.info(f"配置文件已保存: {config_path}")
            return True
        except Exception as e:
            logging.error(f"保存配置文件失败: {e}")
            return False
    
    @classmethod
    def to_dict(cls, config: Config) -> Dict[str, Any]:
        """
        将配置对象转换为字典
        
        Args:
            config: Config 对象
            
        Returns:
            配置字典
        """
        return asdict(config)
    
    @classmethod
    def update_config(cls, config: Config, updates: Dict[str, Any]) -> Tuple[Config, List[str]]:
        """
        更新配置
        
        Args:
            config: 当前配置对象
            updates: 要更新的字段字典
            
        Returns:
            (新配置对象, 错误信息列表)
        """
        # 合并配置
        current_dict = asdict(config)
        current_dict.update(updates)
        
        # 验证
        is_valid, errors = ConfigValidator.validate(current_dict)
        if not is_valid:
            return config, errors
        
        # 过滤掉 Config 类不认识的字段
        valid_fields = {f.name for f in fields(Config)}
        filtered_data = {k: v for k, v in current_dict.items() if k in valid_fields}
        
        return Config(**filtered_data), []
    
    @classmethod
    def get_config_groups(cls) -> Dict[str, List[str]]:
        """
        获取配置字段分组信息
        
        Returns:
            分组字典 {组名: [字段名列表]}
        """
        return {
            "连接配置": ["futu_host", "futu_port", "database_path"],
            "交易配置": ["update_interval", "auto_trade", "price_change_threshold", "volume_surge_threshold"],
            "预警配置": ["alert_5min_rise_threshold", "alert_5min_fall_threshold",
                        "alert_5min_amplitude_threshold", "price_history_duration",
                        "alert_cooldown_seconds", "alert_percent_increment_threshold"],
            "监控配置": ["max_stocks_monitor", "max_subscription_stocks", 
                        "kline_priority_enabled", "log_kline_detail"],
            "优先级配置": ["priority_thresholds"],
            "数据限制配置": ["max_recent_signals", "max_active_stocks", "max_subscribed_stocks",
                          "max_plate_stocks", "max_quality_plates", "max_target_plates",
                          "kline_days", "max_kline_records", "stocks_per_plate",
                          "max_stocks_for_kline_update", "max_stocks_for_trading"]
        }
