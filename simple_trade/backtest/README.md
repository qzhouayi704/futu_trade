# 港股回测系统

一个通用的股票回测框架，支持多种策略的回测和参数优化。

## 快速开始

### 基准回测

```bash
python scripts/run_low_turnover_backtest.py --start 2024-02-06 --end 2025-02-06
```

### 参数优化

```bash
python scripts/run_low_turnover_backtest.py --optimize --mode single
```

## 核心特性

- ✅ **通用架构**：核心组件可被所有策略复用
- ✅ **策略扩展**：只需继承基类即可添加新策略
- ✅ **参数优化**：支持单维度和全量网格搜索
- ✅ **详细报告**：生成Markdown、CSV、JSON多种格式报告

## 目录结构

```
simple_trade/backtest/
├── core/                   # 通用核心组件
│   ├── engine.py          # 回测引擎
│   ├── data_loader.py     # 数据加载器
│   ├── analyzer.py        # 结果分析器
│   └── reporter.py        # 报告生成器
├── strategies/            # 策略实现
│   ├── base_strategy.py   # 策略基类
│   └── low_turnover_strategy.py  # 低换手率策略
└── optimizer.py           # 参数优化器
```

## 已实现策略

### 低换手率策略

测试在低吸位且换手率低的情况下，股票未来上涨的概率。

**买入条件**：
1. 股票处于近N日最低点
2. 当天换手率 < 阈值

**成功标准**：
- 未来N日内最高涨幅 >= 目标涨幅

## 文档

详细使用文档请查看：[docs/回测系统使用文档.md](docs/回测系统使用文档.md)

## 如何添加新策略

1. 继承 `BaseBacktestStrategy` 类
2. 实现 `check_buy_signal()` 和 `check_exit_condition()` 方法
3. 创建对应的回测脚本

详见文档中的"如何添加新策略"章节。

## 输出示例

### 回测报告

```
# 港股回测报告

## 回测参数
- 回测时间范围: 2024-02-06 至 2025-02-06
- 股票市场: HK
- 策略名称: 低换手率策略

## 回测结果
- 总信号数: 156
- 达标次数: 89
- 胜率: 57.05%
- 平均涨幅: 6.23%
- 最大涨幅: 28.45%
```

### 参数对比

系统会自动测试多种参数组合，找出最优配置。

## 技术栈

- Python 3.8+
- pandas: 数据处理
- SQLite: 数据存储
- 富途OpenAPI: 数据获取

## 作者

Warp AI

## 更新日志

### v1.0.0 (2025-02-06)

- ✅ 实现通用回测框架
- ✅ 实现低换手率策略
- ✅ 支持参数优化
- ✅ 生成多格式报告
