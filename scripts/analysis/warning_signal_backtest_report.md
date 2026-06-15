# 预警信号回测报告（vs 安慰剂对照）

> 生成：2026-06-15。脚本 `scripts/analysis/backtest_warning_signals.py`，在**生产库**只读运行。
> 窗口：2026-06-08 ~ 06-12（仅这 5 天有充足逐笔数据）。
> 方法：每条真实信号 + 同股同日随机时间的安慰剂对照（controls=3/6 两次结果一致）。
> 命中阈值 |1.0%|。`retLift`/`liftpp` = 信号相对"随机同日入场"的超额（越大=越有边际）。

## 结论表

| 信号 | 方向 | n | 信号 avgEOD | 对照 avgEOD | EOD命中率提升 | 次日提升 | 判定 |
|---|---|---|---|---|---|---|---|
| flow_sell_r3（流入不足逢高卖） | 看跌 | 174 | −0.56% | +1.17% | **+28.7pp** | +13.7pp | **保留** |
| flow_sell_r2（净流出卖出） | 看跌 | 69 | −0.37% | +1.52% | **+27.8pp** | +26.8pp | **保留** |
| flow_sell_r10（量价背离） | 看跌 | 415 | −0.18% | +0.81% | **+22.2pp** | +12.5pp | **保留** |
| flow_sell_r13（日内波段高抛） | 看跌 | 5 | −3.66% | +0.48% | +73pp | +33pp | 样本不足(暂保留) |
| broker_trap（mega_buy 席位警示） | 看跌 | 920 | +0.57% | +0.67% | +1.1pp | +0.6pp | **降级（无边际）** |
| accumulation_signal（席位确认/主力吸筹） | 看涨 | 3780 | +0.50% | −0.19% | +5.3pp | +7.5pp | 降级（弱，已停产） |
| distribution_trap（出货陷阱） | 看跌 | 3592 | +0.46% | −0.10% | **−8.5pp** | −7.6pp | **反向（劣于随机）** |
| dump（放量下跌） | 看跌 | 445 | +0.46% | −1.24% | **−9.0pp** | −6.1pp | **反向（劣于随机）** |
| absorption（买入吸收） | 看跌 | 295 | +0.57% | −0.50% | **−20.2pp** | −9.1pp | **反向（劣于随机）** |

## 关键发现

1. **资金流卖出规则 R2/R3/R10 确有边际**——这与"信号不准"的直觉相反。原因：之前未加对照时，报警后"平均还涨 +2%"只是因为大盘当期普涨；一旦用同股同日随机入场做对照，这些 SELL 信号后的走势显著弱于随机（命中率高出 +22~29pp，次日仍高 +12~27pp）。**应保留其在 `pre_trade_check` 中的扣分门控。**

2. **真正坏的是经纪商席位/吸收系信号**：
   - **买入吸收（absorption）−20pp、放量下跌（dump）−9pp、出货陷阱（distribution_trap）−8.5pp 全部反向**——报警后价格反而比随机更强。其中买入吸收最离谱：发"压单出货"警报后股价多数上涨（典型的吸筹进行中被误判为出货）。
   - **mega_buy 席位警示（broker_trap）+1pp，等于随机**——只是给 mega_buy 增加噪音和前端复杂度。

3. **方法学教训**：commit `16ffaff` 当初判 distribution_trap "near random / 63%" 缺少对照基准；本次用安慰剂对照后，distribution_trap 实为**劣于随机**，停产正确；并且仍在 `decision/engine.py:582` 硬阻断买入的同款检测应当一并移除。

## 落地动作（数据驱动）

- **杀掉 distribution_trap 买入硬门**：`decision/engine.py:582-585`（劣于随机却在拦单）。
- **剥离 mega_buy 的席位警示/确认标签与降级**：`sniper/intraday_sniper.py:264-314`（无边际，只增噪音/复杂度）。
- **买入吸收(absorption) + 放量下跌(dump) 均降级为中性"观察"提醒**：`analysis/absorption_scanner.py` 保留检测、`quote_pipeline.py` 去掉🚨看跌措辞(改 👀 量价观察)但保留 ALERT 类型 → 持续写入 `signal_pipeline`(direction=WARN) 供数日后复跑回测；前端 `UnifiedSignalFeed.tsx` 以 👀 灰色 urgency=40 低优先级展示，不报红、不参与交易。是否反转成看涨信号待更多行情数据。
- **保留** 资金流 SELL R2/R3/R10 的门控与扣分（`pre_trade_check.py:426-434`、`flow_signal_rules.py`）——有边际。
- 前端据此精简（全部前端信号面）：
  - 主信号流 `UnifiedSignalFeed.tsx`：配色统一为三语义桶(买入机会绿/风险卖出红/仅参考观察灰)，买入吸收/放量下跌→灰色观察，动量标签中文化。
  - `GlobalSignalListener.tsx`：买入吸收/放量下跌不再弹 Toast 打扰。
  - `sniper-signals/page.tsx`：移除 distribution_trap/accumulation_signal 主信号卡片/筛选/统计(已停产)。
  - `IntradayLevelsPanel.tsx`：买入吸收横幅去掉"需警惕主力出货"看跌结论与红色高危样式，改中性"仅参考"。
  - `MarketScanPanel.tsx`：③ 席位检测不再红色告警"出货陷阱"，改中性"仅参考"。
  - (注：`AlertsCard/SniperCard/PositionFlowCard/PlateAlertsCard` 为未挂载的遗留组件，未改。)

## 持续记录与复跑（用于过几天看效果）

- absorption_scanner 的买入吸收/放量下跌仍写入 `signal_pipeline`(source='absorption_scanner', direction='WARN', 含 timestamp/stock/price/raw_detail)，降级为中性后**记录不中断**。
- 资金流 SELL 写入 `capital_flow_signals`；mega_buy/mega_sell 写入 `sniper_signals` — 均持续记录。
- 数日后复跑：`python3 - --days 20 --controls 6 --categories absorption,flow_sell < scripts/analysis/backtest_warning_signals.py`（生产只读），对比新窗口的 lift 是否仍反向/有边际。

## 复跑命令

```bash
# 只读，在生产服务器：
ssh -i ~/.ssh/id_ed25519_server -p 29122 root@<host> \
  'cd /opt/futu_trade_sys && python3 - --days 15 --controls 6' \
  < scripts/analysis/backtest_warning_signals.py
# 体检模式（只看各类条数）：加 --probe
```
