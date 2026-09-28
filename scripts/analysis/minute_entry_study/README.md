# 分钟入场规则研究

研究报告：`discuss/minute-entry-study-results-20260924.md`。正式结果目录为 `backtest_results/minute-entry-study-20260924-v3`；v1/v2 是精度检查和分阶段订单时序检查期间的中间输出。

## 运行

Linux 项目环境可运行：

```bash
bash scripts/run_minute_entry_study.sh \
  --input backtest_results/minute-entry-20260901-20260923.json.gz \
  --output backtest_results/minute-entry-study-new-run
```

本次 Windows `.venv` 启动器失效，使用现有打包运行时，不安装依赖、不修改虚拟环境：

```powershell
uv --cache-dir 'backtest_results/uv-cache' run --offline --no-project --python 'C:\Users\ZHOUYICAN\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' python -m scripts.analysis.minute_entry_study.run --input backtest_results/minute-entry-20260901-20260923.json.gz --output backtest_results/minute-entry-study-new-run
```

将上面模块替换为 `unittest tests.v2.test_minute_entry_study -v` 可运行15项因果与费用测试。输出目录必须不存在，研究输入与旧报告不会覆盖。

`export.py` 是有查询时限、范围和行数上限的只读生产导出。`fetch.py` 经 SSH 标准输入执行，不向生产服务器写脚本。历史输入已经保存，无需为了复跑再次访问服务器。`focus.py` 仅将冻结规则用于今天的独立案例，`diagnostics.py` 的配对归因不参与选参。

## 范围

- 对真实候选事件之后的分钟重新计算价格突破、低位回升、主动买盘规则。
- 原有正式/全部确认、观察事件作为入场对照；没有声称完整重算生产 V2 的每笔大单和所有状态。
- 每只股票每天最多一次首次入场；训练选择后再评估25%/50%试探仓与正式确认加仓。
- 数据价为分钟成交均价，VWAP由均价乘成交量近似；不是实际盘口或真正分钟收盘价。
- 事件按接收/交易所时间较晚者可用，分钟结束后1秒决策，之后开始的完整分钟才能成交。
- 每笔正常额度假定10000港元，最多参与完整分钟估计成交额10%，容量不足时限期等待；这是完整单假设，不模拟部分成交、排队或真实手数。
- 缺失分钟不补齐，无法退出不计为0收益或强行平仓。行情缺口会影响排序，所以报告包括无缺口子样本和未退出数量。
- 0.15%每边费用与0.05%每边滑点为研究情景；另测高成本和最高价买/最低价卖情景。

`trades.csv` 的 `net` 是相对于完整正常额度的收益。试探仓只投入25%时，损益大致缩小到四分之一；不能直接把它解释成单位已投入资本的策略改善。
