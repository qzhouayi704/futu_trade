# 交易策略模块

本模块包含交易策略的实现，包括策略基类、策略注册器和具体策略实现。

## 📁 文件结构

```
strategy/
├── __init__.py                    # 模块初始化，导出所有策略类
├── base_strategy.py               # 策略抽象基类
├── strategy_registry.py           # 策略注册器
├── swing_strategy.py              # 低吸高抛策略
├── trend_reversal_strategy.py     # 趋势反转策略（新）
├── analyze_cases.py               # 买卖点案例分析脚本
├── backtest_strategy.py           # 策略回测脚本
└── README.md                      # 本文档
```

## 🎯 策略列表

### 1. 低吸高抛策略 (SwingStrategy)

- **策略ID**: `swing`
- **默认策略**: 是

基于12日高低点的技术分析策略：
- **买入条件**: 今日最低价 > 昨日最低价 且 昨日最低价 = 近12日最低点
- **卖出条件**: 今日最高价 < 昨日最高价 且 昨日最高价 = 近12日最高点

### 2. 趋势反转策略 (TrendReversalStrategy) ⭐新

- **策略ID**: `trend_reversal`
- **默认策略**: 否

基于趋势反转的买卖点识别策略：

#### 买点条件
1. 近N日下跌天数占比 ≥ 60%（阴线为主）
2. 距期间最高点跌幅 ≥ 8%
3. 反弹信号（距最低点涨幅）≥ 2%
4. 今日K线为阳线（反转确认）

#### 卖点条件
1. 近N日上涨天数占比 ≥ 60%（阳线为主）
2. 距期间最低点涨幅 ≥ 10%
3. 回落信号（距最高点跌幅）≥ 2%
4. 今日K线为阴线（反转确认）

#### 止损条件
1. 跌幅超过 5%
2. 持有3天后趋势未延续（上涨天数 < 40%）

#### 策略参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `lookback_days` | 回看天数 | 10 |
| `min_drop_pct` | 买点最小跌幅(%) | 8.0 |
| `min_rise_pct` | 卖点最小涨幅(%) | 10.0 |
| `min_reversal_pct` | 最小反转信号(%) | 2.0 |
| `max_up_ratio_buy` | 买点最大上涨天数比例 | 0.4 |
| `min_up_ratio_sell` | 卖点最小上涨天数比例 | 0.6 |
| `stop_loss_pct` | 止损阈值(%) | -5.0 |
| `stop_loss_days` | 止损判断天数 | 3 |

## 🔧 使用方法

### 1. 直接使用策略类

```python
from simple_trade.strategy import TrendReversalStrategy

# 创建策略实例
strategy = TrendReversalStrategy(
    data_service=stock_data_service,
    config={
        'lookback_days': 10,
        'min_drop_pct': 8.0,
        'min_rise_pct': 10.0
    }
)

# 检查交易信号
result = strategy.check_signals(
    stock_code='US.AAPL',
    quote_data={
        'last_price': 150.0,
        'high_price': 152.0,
        'low_price': 148.0,
        'open_price': 149.0
    },
    kline_data=kline_list
)

if result.buy_signal:
    print(f"买入信号: {result.buy_reason}")
elif result.sell_signal:
    print(f"卖出信号: {result.sell_reason}")
```

### 2. 通过策略注册器

```python
from simple_trade.strategy import StrategyRegistry

# 获取所有可用策略
strategies = StrategyRegistry.list_strategies()
print(strategies)

# 创建指定策略实例
strategy = StrategyRegistry.create_instance(
    strategy_id='trend_reversal',
    data_service=stock_data_service,
    config=config
)
```

### 3. 检查止损

```python
# 检查是否需要止损
stop_loss_check = strategy.check_stop_loss(
    stock_code='US.AAPL',
    buy_price=150.0,
    buy_date='2024-01-15',
    current_data={'last_price': 145.0},
    kline_since_buy=kline_list
)

if stop_loss_check.should_stop_loss:
    print(f"止损信号: {stop_loss_check.reason}")
```

## 📊 案例分析脚本

分析给定买卖点案例的详细数据指标：

```bash
# 运行案例分析
python simple_trade/strategy/analyze_cases.py --lookback 10 --output case_analysis_report.json
```

### 参数说明
- `--host`: 富途API主机地址（默认: 127.0.0.1）
- `--port`: 富途API端口（默认: 11111）
- `--lookback`: 回看天数（默认: 10）
- `--output`: 输出报告文件路径

### 案例列表
1. 美团(MPNGY): B 2025-07-10, S 2025-07-18
2. 富途控股(FUTU): B 2025-10-14, S 2025-11-03
3. 拼多多(PDD): B 2025-04-10, S 2025-05-14
4. 特斯拉(TSLA): B 2025-03-20, S 2025-05-27
5. 小鹏汽车(XPEV): B 2025-05-27（止损案例）

## 📈 回测脚本

使用历史数据对策略进行回测验证：

```bash
# 运行回测
python simple_trade/strategy/backtest_strategy.py \
    --start 2024-01-01 \
    --end 2024-12-31 \
    --lookback 10 \
    --min-drop 8.0 \
    --min-rise 10.0 \
    --output backtest_report.json
```

### 参数说明
- `--start`: 回测开始日期（默认: 2024-01-01）
- `--end`: 回测结束日期（默认: 2024-12-31）
- `--lookback`: 回看天数（默认: 10）
- `--min-drop`: 最小跌幅(%)（默认: 8.0）
- `--min-rise`: 最小涨幅(%)（默认: 10.0）
- `--min-reversal`: 最小反转信号(%)（默认: 2.0）
- `--output`: 输出报告文件路径

### 回测股票列表（默认）
- US.AAPL（苹果）
- US.TSLA（特斯拉）
- US.NVDA（英伟达）
- US.GOOGL（谷歌）
- US.META（Meta）
- US.AMZN（亚马逊）
- US.MSFT（微软）
- US.BABA（阿里巴巴）
- US.JD（京东）
- US.PDD（拼多多）

## ⚙️ 配置文件

策略参数在 `config.json` 中配置：

```json
{
  "strategy": {
    "active_strategy": "trend_reversal",
    "swing": {
      "lookback_days": 12
    },
    "trend_reversal": {
      "lookback_days": 10,
      "min_drop_pct": 8.0,
      "min_rise_pct": 10.0,
      "min_reversal_pct": 2.0,
      "max_up_ratio_buy": 0.4,
      "min_up_ratio_sell": 0.6,
      "stop_loss_pct": -5.0,
      "stop_loss_days": 3
    }
  }
}
```

## 📋 开发新策略

1. 继承 `BaseStrategy` 基类
2. 实现 `name`、`description` 属性
3. 实现 `check_signals` 方法
4. 使用 `@register_strategy` 装饰器注册策略

```python
from .base_strategy import BaseStrategy, StrategyResult
from .strategy_registry import register_strategy

@register_strategy("my_strategy", is_default=False)
class MyStrategy(BaseStrategy):
    @property
    def name(self) -> str:
        return "我的策略"
    
    @property
    def description(self) -> str:
        return "策略描述"
    
    def check_signals(self, stock_code, quote_data, kline_data) -> StrategyResult:
        result = StrategyResult(stock_code=stock_code)
        # 实现策略逻辑
        return result
```

## ⚠️ 风险提示

本策略仅供参考，不构成投资建议。股票市场存在风险，投资需谨慎。
