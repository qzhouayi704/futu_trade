# Futu Trade System 开发与调试进度记录 (RETIDO)

## 📌 当前最新进度 (2026-06-09)

### 1. 紧急修复：经纪商一致性过滤失效问题 (Commit `6b51943`)
* **问题现象**：盘中信号的席位分析标签全部被分类为 `"散户/未知席位主导"`，没有出现 `"机构吸筹中"` 或 `"存在出货迹象"` 标签。
* **根因定位**：
  在 `simple_trade/services/sniper/intraday_sniper.py` 和 `simple_trade/services/trading/decision/engine.py` 中实例化 `BrokerConsistencyFilter(container)` 时，错误地传入了 `ServiceContainer` 实例，而非 `FutuClient`。
  由于 `BrokerConsistencyFilter` 内部通过 `getattr(self._futu_client, 'client', None)` 获取底层 SDK 客户端，而 `ServiceContainer` 并没有 `client` 属性（只有 `container.futu_client` 指向 `FutuClient`，其内部才含有 `client`），这导致过滤逻辑因 `self._client is None` 而静默返回默认的未识别状态。
* **修复内容**：
  将所有 5 处 `BrokerConsistencyFilter(self.container)` 修改为 `BrokerConsistencyFilter(self.container.futu_client)`：
  * `simple_trade/services/sniper/intraday_sniper.py` (3 处)
  * `simple_trade/services/trading/decision/engine.py` (2 处)
* **生产部署与验证**：
  * 修复版本已部署至生产环境 (`170.106.152.108`)。
  * 检查 `/opt/futu_trade_sys/logs/backend.log` 确认席位过滤逻辑正常运行。
  * 验证成功：新产生的信号正确识别出三种席位分析结果，例如：
    * 🟢 **主力吸筹中**：万国数据-SW (50%)、英恒科技 (65%)、浙江世宝 (60%) 等。
    * 🔴 **存在出货迹象**：天数智芯 (70%)、健康160 (60%)、华夏恒生生科 (50%) 等。

---

## 🔍 个股实时席位分析 (金山软件 & 中芯国际)

根据生产服务器 2026-06-09 日内运行日志分析：

### 1. 金山软件 (HK.03888)
* **当前状态**：**主力吸筹 (置信度 60%)** 🟢
* **详细特征**：
  * **买方专业席位**：`[中信証券经纪(香港)有限公司(机构), 花旗环球金融亚洲有限公司(机构), 中国投资信息有限公司(北水)]`
  * **卖方散户席位**：`[盈透证券香港有限公司]`
  * **资金与指标**：触发 `[R11] 资金持续流入` 指标，连续 3 日资金净流入，累计净流入 5747 万，趋势性吸筹特征明显，但当前 K 线处于相对高位 (84%)。

### 2. 中芯国际 (HK.00981)
* **当前状态**：**量价背离 / 逢高卖出预警** ⚠️
* **详细特征**：
  * 今日未触发狙击手 (`sniper`) 席位信号，因此没有席位归类日志。
  * **资金与指标**：
    * 13:48 触发 `[R3] 流入不足逢高卖` 预警：价格虽上涨，但资金净流入仅 3.02 亿（占日均交易额 2.9% < 3%），上涨动力不足。
    * 13:53 及 14:14 触发 `[R10] 量价背离` 预警：价格接近日高，但成交额仅为日均成交的 58%，存在量价背离迹象。

---

## 🛠️ 近期其他主要提交

1. **优化巨量抢筹席位校验 (Commit `4a12297`)**
   * 修复 `change_pct` 的硬编码问题。
   * 消除重复的富途 API 接口调用，优化高频扫描下的性能。
2. **持仓 AI 诊断 (Commit `11b5fc1`)**
   * 后端新增 `POST /api/ai-analysis/position/{code}`，聚合 15 维数据 (包括 `pipeline_records` + `sniper_history`)，调用 Gemini 分析提供止盈止损建议。
   * 前端持仓卡片集成 "AI诊断" 按钮及结构化弹窗展示。
3. **信号去重与非交易时段守卫 (Commit `0578daa`)**
   * 在 `pipeline_broadcast` 模块添加同一股票+策略+方向 10 分钟内不重复写入去重逻辑。
   * 在 `quote_pipeline` 模块中的 `_should_run_strategy` 引入守卫，非交易时段直接返回 `False`，避免无效计算。

---

## 📅 后续待办事项 (TODO)

- [ ] **高并发稳定性验证**：监控在盘中高频产生信号时，`BrokerConsistencyFilter` 对富途 API 限流的消耗情况。
- [ ] **持仓 AI 诊断优化**：观察 Gemini 给出的止盈止损建议，并根据实际交易表现微调 15 维数据的输入模版。
- [ ] **AkShare 数据源引入计划**：解决富途历史 K 线下载限额瓶颈，引入外部免费接口（如 AkShare 等）来同步全市场静态 K 线。
