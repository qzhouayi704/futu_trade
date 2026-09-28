# 主题跨日分钟研究（离线）

完整方案：`discuss/thematic-swing-backtest-plan-20260924.md`。该目录不导入生产交易服务，不修改线上策略、不下单。

## 运行

Windows PowerShell 中使用已有 Git Bash；Python 和 NumPy 复用已安装运行时，`uv --offline --no-project` 防止安装依赖。项目 `.venv` 当前启动失败，可通过 `SWING_PYTHON` 指定另一个已有可用 Python。

```powershell
& 'D:/Program Files/Git/bin/bash.exe' scripts/run_swing_study.sh test
& 'D:/Program Files/Git/bin/bash.exe' scripts/run_swing_study.sh fetch --output backtest_results/new-input.json.gz
& 'D:/Program Files/Git/bin/bash.exe' scripts/run_swing_study.sh run --input backtest_results/thematic-swing-20260901-20260923.json.gz --output backtest_results/new-swing-run
& 'D:/Program Files/Git/bin/bash.exe' scripts/run_swing_study.sh verify --input backtest_results/thematic-swing-20260901-20260923.json.gz --output backtest_results/new-swing-run
& 'D:/Program Files/Git/bin/bash.exe' scripts/run_swing_study.sh inspect --report backtest_results/new-swing-run/report.json
```

`fetch` 只读访问服务器，最多2次尝试、每次150秒上限；远端查询有120秒上限且只读事务。输出禁止覆盖。研究日志打印到控制台，完整机器可复核结果在输出目录；不接入生产日志或生命周期。

## 口径

- 18个入场、24个退出，共432组训练。固定1/3/5日情景仅描述，不按留出收益选择上线参数。训练5个入场日期、留出4个入场日期，另留足退出时间；样本并非此前从未观察的盲测。
- 候选只在事件当时主标签属于五主题后才能使用；不以当前多标签补历史。低位与资金启动都是候选内再筛选，不是重新扫描全市场。
- 日线背景要求此前21条唯一有效日线。14日ATR、20日位置/均额和5/20日均线只取此前日期；日期归一后同日OHLC差异超过0.5%标记冲突，用到冲突背景的候选跳过。档案有后补/前复权且缺少当时版本，不等于日线数据完全点时可复现。
- 分钟价是逐笔均价，不是OHLC收盘价。信号在分钟结束+1秒才可用，之后首个完整分钟开始模拟；没有同分钟成交。入场最多等待5个交易分钟，退出挂单跨日等待；行情空缺不填价。
- 入场每票1万港元，最多占分钟成交额10%，退出按实际模拟股数检查容量；未处理真实手数、队列、买卖价差、停牌原因、股息和公司行动。
- 固定风险距离为 `clip(ATR百分比×1或1.5, 2%, 10%)`，目标2R/3R；可选峰值达到+1R后启动1.5ATR移动保护。同分钟止损与止盈同时触发优先止损，最终成交仍按之后行情。
- 持有天数包含入场日，最后一天15:49发出时间退出；没有成交可延期或保持未退出，不强行释放资金。未退出交易不计为零收益。
- 每股每策略不允许跨日持仓重叠。单票指标没有总持仓上限；组合另模拟10万本金、固定1万/票、最多5票、先到先得，同刻代码排序，无杠杆。无缺口完整盯市才给严格最大回撤，否则为null。
- `focus_cases` 为指定两只股票所有可观察候选的独立路径实验，可重叠，绝不可汇总为组合收益；CSV中的策略路径已去除同股持仓重叠。
- 缺口条件样本是事后数据敏感性检查，不是可交易筛选。4个入场日期且跨日收益重叠，日期聚类区间不支持正式显著性判断。

最终产物采用 `thematic-swing-study-20260924-v2`；v1保留为中间检查结果，不覆盖。

## 历史覆盖审计

`audit/` 只导出/检查覆盖与历史证据，不产生收益回测。审计窗口固定为2026-06-15至09-23；较早日线用于背景核对。远端 SQLite 为只读、有查询超时与行数上限，不修改采集配置。最后两条可完全离线运行：

```powershell
& 'D:/Program Files/Git/bin/bash.exe' scripts/run_swing_study.sh fetch --audit --output backtest_results/new-history-audit.json.gz
& 'D:/Program Files/Git/bin/bash.exe' scripts/run_swing_study.sh fetch --audit-legacy --output backtest_results/new-legacy-themes.json.gz
& 'D:/Program Files/Git/bin/bash.exe' scripts/run_swing_study.sh audit.run --input backtest_results/history-audit-20260615-20260923.json.gz --legacy backtest_results/history-legacy-themes-20260924.json.gz --output backtest_results/new-history-readiness
& 'D:/Program Files/Git/bin/bash.exe' scripts/run_swing_study.sh audit.verify --input backtest_results/history-audit-20260615-20260923.json.gz --legacy backtest_results/history-legacy-themes-20260924.json.gz --output backtest_results/new-history-readiness
```

当前最终产物为 `backtest_results/history-readiness-20260924-v3/`，结论见 `discuss/history-data-readiness-20260924.md`。V2 的17日与旧版事件时标签的52日分开解释；覆盖分层不是未来可知的交易选池条件，330分钟有记录也不是逐笔完整性证明。旧标签中无光伏，仅表示该历史来源缺样本。

## 旧版52日独立回放

`legacy/` 解析当时的FIRST及后续序列，不与V2候选拼接；保留全部后续分钟和失效事件。口径及结果：`discuss/legacy-swing-replay-20260924.md`。

```powershell
& 'D:/Program Files/Git/bin/bash.exe' scripts/run_swing_study.sh fetch --legacy-replay --output backtest_results/new-legacy-input.json.gz
& 'D:/Program Files/Git/bin/bash.exe' scripts/run_swing_study.sh legacy.run --input backtest_results/legacy-swing-20260714-20260923.json.gz --audit-only
& 'D:/Program Files/Git/bin/bash.exe' scripts/run_swing_study.sh legacy.run --input backtest_results/legacy-swing-20260714-20260923.json.gz --output backtest_results/new-legacy-run
& 'D:/Program Files/Git/bin/bash.exe' scripts/run_swing_study.sh legacy.verify --input backtest_results/legacy-swing-20260714-20260923.json.gz --output backtest_results/new-legacy-run
```

最终采用 `backtest_results/legacy-swing-study-20260924-v3/`，日志 `logs/legacy_swing_study.log`。96组合×3轮扩展窗口，只用训练选择；连续固定规则的持仓不会在分段边界释放。配对序列可重叠，只作条件诊断。正式确认区分技术阶段与通知动作，仅观察事件不是实盘买令。没有修改生产策略或订阅，不启用交易。

## 前瞻协议与只读就绪检查

`forward.run` 只登记冻结参数、摘要和可用日期，**不启动采集/模拟，不计算前瞻收益**。当前已登记协议，不要每次检查时重新登记来改变开始边界：

```powershell
& 'D:/Program Files/Git/bin/bash.exe' scripts/run_swing_study.sh fetch --forward-readiness --output backtest_results/new-readiness-probe.json.gz
& 'D:/Program Files/Git/bin/bash.exe' scripts/run_swing_study.sh forward.run --probe backtest_results/new-readiness-probe.json.gz --protocol backtest_results/forward-protocol-20260924/protocol.json --output backtest_results/new-forward-check
```

首次登记才使用 `--historical-input` 替代 `--protocol`。检查会核验同目录 `provenance.json` 中的规范化协议摘要；不覆盖已有输出。日历仅支持已核对的2026-09-24至12-23完整时段；归档存在不等于单票数据合格，结果就绪状态不会自动置为通过。报告见 `discuss/forward-study-readiness-20260924.md`；日志 `logs/forward_study_readiness.log`。

## 默认关闭的跨日研究内核（本地）

`forward/runtime/` 是独立的类型化事件仓库、跨日跟踪和收盘回放适配器，不接入生产服务、Futu SDK、订阅或下单接口。默认命令仅返回关闭状态；下面第二条必须明确选择本地合成演示，且输出目录不得已存在：

```powershell
& 'D:/Program Files/Git/bin/bash.exe' scripts/run_swing_study.sh forward.runtime.cli
& 'D:/Program Files/Git/bin/bash.exe' scripts/run_swing_study.sh forward.runtime.cli --enable-local --demo --protocol backtest_results/forward-protocol-20260924/protocol.json --output backtest_results/new-cross-day-demo
& 'D:/Program Files/Git/bin/bash.exe' scripts/run_swing_study.sh test
```

本轮最终合成产物为 `backtest_results/cross-day-runtime-demo-20260928-v2/`，日志 `logs/cross_day_research.log`。演示中的股票代码、日期只是测试载体，**价格和所有输入均为虚构，包括尚未发生的日期，不能用于判断 HK.00100/HK.00699 的收益或买卖**。v1 为开发中间输出，勿用它恢复最新事件模型。

- 事件源接口：`Collector.observe(Event)`；强类型信号、完成分钟、盘前日线快照、连续性心跳、收盘持仓占用。真实采集入口尚未接线；CLI 当前只提供合成演示，不支持偷偷导入历史数据冒充前瞻采集。
- 独立 SQLite 必须匹配专用标识、协议摘要、数据种类；禁止覆盖生产数据库。单写入者，2 秒锁等待；最大 20 万事件、主库 128 MiB，超限显式报错。SQLite 临时回滚日志另占磁盘，不是总磁盘用量限额。
- 事务提交后更新内存；重复事件幂等；同一股票分钟/盘前快照的冲突修订拒绝。重启恢复跟踪和研究占用，资金账本由不可变事件前缀重新回放恢复，不是线上逐笔订单账本。
- FIRST 至少跟踪 5 个交易日；失效信号不清除研究跟踪，持仓/待退出继续保留。超过期限但缺少覆盖期限末日的收盘核对，也继续保留，不能把“未回放”当作“已经平仓”。订阅选择仅输出建议，优先保留传入的真实持仓代码，额满明确列出未能安排的研究代码。
- 收盘回放只接受当日16:30及之后的 `as_of`，保留缺失交易日；信号按接收时间可用，日线须在开盘前收到，分钟超过完成后1秒才收到则保留但剔除回放。此严格可用性口径属于新采集适配层，不能把旧归档文件直接标记成合格前瞻数据。
- 四组规则及资金/成交约束沿用9月24日冻结源码，不重新挑参数；报告独立记录适配器摘要。缺数据不补价，未退出收益为null，没有任何成交证据也不报告测得的零收益。
- 报告中的 `exposures` 由编排方显式追加到仓库（CLI 已演示）；同一输入/同一收盘时点重复核对不新增事件。心跳仅说明接收到连接状态，`wall_clock_gaps` 包含闭市间隔，不可直接当作盘中漏采；零累计量报告也不等于已完成逐笔对账认证。

9月24日的 `forward.run` 就绪判断及其“适配器未实现”诊断属于被冻结的原代码口径，本轮未改写该历史基线。新增内核报告为 `LOCAL_EOD_REPLAY_NOT_LIVE_CERTIFIED`；本地实现通过不代表真实采集、逐笔完整性或策略收益已验证，也不会自动解除任何上线门禁。

## 真实来源诊断与隔离接入

`forward/intake/` 对生产字段做强类型转换和证据核验。`LiveSignalIngress` 是默认关闭的工作线程侧信号接口，必须传入稳定源事件ID和首次接收时刻；**本轮未接线至生产回调**。不允许用落库/归档时间冒充 SDK 接收时间，不把旧提醒补成FIRST，不改变冻结参数。

```powershell
# 有权限的服务器只读导出：固定三股 HK.00100/HK.00699/HK.03317，最近14天至当天。
& 'D:/Program Files/Git/bin/bash.exe' scripts/run_swing_study.sh fetch --forward-intake --output backtest_results/new-source-intake.json.gz
# 默认只做本地审计；显式加 --stage-diagnostic-signals 才建立隔离库，输出不能覆盖。
& 'D:/Program Files/Git/bin/bash.exe' scripts/run_swing_study.sh forward.intake.cli --input backtest_results/forward-source-intake-20260928.json.gz --protocol backtest_results/forward-protocol-20260924/protocol.json --output backtest_results/new-source-audit
```

源数据库 `mode=ro` + `query_only`，查询25秒上限、读取锁等待3秒；复用现有最多2次/每次150秒的SSH传输。聚合分钟只取常规时段；逐笔每股最新200条、日线元数据每股最新22条均只是合同诊断样本，不能解释为完整路径。信号最多5000条且超限失败；压缩与解压体积都受8MiB限制。仅股票/行情/信号字段，无环境变量、凭证或账户导出。

归档诊断库绑定 `ARCHIVE_DIAGNOSTIC`，不得与 `LOCAL_OBSERVATIONS`/`SYNTHETIC` 混用；Collector 拒绝跨种类观察，回放也拒绝诊断源（含误传默认种类时）。归档缺接收证据、日线缺点时版本、连接/丢包历史不全，始终保留非就绪状态。显式导入仅支持可标准化的旧版序列信号，不导入归档分钟做前瞻收益。

最终实际核验见 `discuss/forward-source-intake-20260928.md`，产物 `backtest_results/forward-source-intake-check-20260928-v3/`：三股25条记录均为普通提醒，无FIRST序列，隔离序列入库0条；不是25条无效行情。全市场阶段汇总未获权限、未执行，不能据三股推断全市场情况。日志 `logs/forward_source_intake.log`。

后续用户已明确授权**仅全港股按日期/阶段的汇总计数**，新增独立入口，不影响三股明细范围：

```powershell
& 'D:/Program Files/Git/bin/bash.exe' scripts/run_swing_study.sh fetch --forward-stage-counts --output backtest_results/new-hk-stage-counts.json.gz
```

该查询只在数据库内读取并分类旧 `capital_trend` 的阶段，不导出股票名单、事件ID、价格或原始JSON；未知自由文本归为OTHER_STAGE，非法JSON/阶段类型另列。25秒查询、3秒锁等待、300分组/128KiB上限，超限拒绝而不交付残缺汇总。实际输出 `backtest_results/hk-legacy-stage-counts-20260928.json.gz`：截至11:36今日2条FIRST、无CONFIRMED；此前三股零FIRST不能推广到全市场。无权据此读取相应股票/事件明细；结果仅代表该数据库来源，不代表完整港股覆盖或V2信号。

用户随后继续授权这2条FIRST及关联序列的必要明细，因此另加 `fetch --forward-two-sequences` 专用诊断入口：固定9月28日11:36:26快照里的两个FIRST，数量或股票数不吻合则失败，仅字段白名单及到首个终止阶段的记录，不读取其他股票、日期或最新新增信号。此授权不改变上述汇总入口或三股入口的范围。产物 `backtest_results/authorized-two-first-sequences-20260928.json.gz`，诊断详见同一报告的“11:42”章节；无分钟收益回测或规则改动。

## 事件时多主题诊断（本地，不改变冻结选池）

```powershell
& 'D:/Program Files/Git/bin/bash.exe' scripts/run_swing_study.sh forward.intake.theme_audit --input backtest_results/authorized-two-first-sequences-20260928.json.gz --protocol backtest_results/forward-protocol-20260924/protocol.json --output backtest_results/new-theme-audit
```

默认不补任何成员标签，缺证据输出UNKNOWN。可选 `--memberships <本地JSON>` 只接受 `schema=1`、`kind=THEME_MEMBERSHIP_DIAGNOSTIC`、`snapshots` 列表；字段见 `forward/intake/themes.py` 的 `MembershipSnapshot` 与 `PlateMembership`。快照须显式提供源ID/版本、采集和首次接收时间（有时区）、完整性、证据类型和成员板块代码/名称。输入只限原两股、最多256快照、128成员/快照及128KiB，不能直接传当前数据库结果冒充历史点时证据。

按信号发生时已经收到的同日最新采集快照判断；缺失、未来取得、非点时来源、不完整或同刻冲突均UNKNOWN。完整证据下才区分MATCHED和EXCLUDED，保留中文解释及冻结单主标签对照。多标签取冻结 `theme_of` 结果的并集，单标签词表/优先级不变；不将结果输入旧回放或生产候选池，MATCHED不是买入许可。来源真实性始终标记未独立认证，当前表覆盖是否完整也需单独验收。

最终产物 `backtest_results/forward-theme-audit-20260928/theme-report.json`：吉利和网易都缺事件时多主题快照，归为UNKNOWN，而非已验证不属于五主题。172项研究测试通过；真实多标签采集回调尚未接线，不产生新收益结果。日志 `logs/forward_theme_audit.log`。

## 后续：采集管道已接线，默认关闭

新增生产侧 `simple_trade/services/research/theme_capture/`，不从生产依赖本研究包。`QuotePipeline` 接受显式可选 `ThemeCapturePort`，检测前请求后台刷新，生成旧版序列信号后、任何广播等待前捕获内部接收时刻和关联快照。`app.lifespan` 已装配可选服务并在退出时排空；本轮仅代码和临时库测试，未启动应用或部署。

默认 `RESEARCH_THEME_CAPTURE_ENABLED=0`，不建库、不查询、不启动线程。未来启用还必须明确指定 `RESEARCH_THEME_CAPTURE_PATH`（已存在父目录中的独立文件）、`RESEARCH_THEME_CAPTURE_CODES`（最多50个HK代码）和 `RESEARCH_THEME_CAPTURE_SOURCE_VERSION`（部署/源版本标识）；主库路径来自现有容器。不提供自动股票池、自动开启或完整性强制通过选项。这些变量本轮均未写入运行配置。

- 源查询只读当前本地多对多关系，100毫秒锁等待、约500毫秒SQL执行预算、每股128成员上限。最多2次尝试，失败后60秒退避并清掉可绑定缓存；无SDK调用或订阅变更。
- 快照先保存再发布缓存；信号必须引用同日且采集接收时刻不晚于信号的版本。没有版本就记缺失，后台后来完成不能回填。源完整性固定false，兼容上面的诊断输入但仍会显示UNKNOWN；不是新策略入场许可。
- 默认256任务队列、10万总记录（含会话）、64MiB主库。独立线程完成磁盘工作；回调只处理有限字段/队列，满队列计数。异常会话不能认定完整；进程异常退出没有结束时刻。日志经应用既有日志配置写入 `logs/backend.log`。
- 独立库校验身份和配置绑定，拒绝主库/其他数据库，保留单写入者独占锁；**采集运行中不支持外部读取该库，停止后再审计**。回滚日志可能另外占空间，64MiB不是总磁盘上限。信号重复保留首次接收/原关联；冲突拒绝。重启保留历史但不把旧缓存冒充新采集。
- 保存的是内部资金信号及本地主题成员证据，不是完整分钟行情、日线版本、SDK接收时间或交易账本；未自动接入冻结收益回放。完整应用启动/停止、真实覆盖和源真实性尚待验收。

### 后续：真实应用模块的隔离启动／停止验收

```powershell
& 'D:/Program Files/Git/bin/bash.exe' scripts/run_theme_capture_smoke.sh check
& 'D:/Program Files/Git/bin/bash.exe' scripts/run_theme_capture_smoke.sh test -v
```

使用项目已有 `.venv/Scripts/python.exe`（本机Python 3.13.3及完整应用依赖），不安装依赖、不启动Web服务器。当前沙箱访问该解释器会失败，经批准执行检查/测试可运行，不能将此误判为虚拟环境损坏。可通过 `THEME_SMOKE_PYTHON` 指定另一个已具备完整应用依赖的兼容解释器，不混用3.12与3.13扩展。

本测试在独立进程正常导入真实应用、全部路由和真实QuotePipeline/ThemeCapture，不再只提取AST方法。配置/SDK日志/SQLite仅指向临时目录，模拟容器外部服务、行情推送启停及不相关后台任务，严格拒绝网络连接/监听及临时目录外数据库访问。实际进入/退出ASGI生命周期并用内存内HTTP访问 `/health`；不测试真实OpenD、账户、交易或部署环境。

### 五股部署验收（2026-09-28）

已授权采集HK.00100、HK.00699、HK.03317、HK.00175、HK.09999；不增加指定股票订阅、不修改交易开关或策略参数。普通测试集合跳过生命周期烟雾测试，由上面的独立脚本设置 `THEME_CAPTURE_ISOLATED_SMOKE=1` 执行，避免其他测试先导入应用导致隔离失效。脚本同时支持Windows和Linux现有虚拟环境，不安装新依赖。

发布前发现初始化误把“有休市回退的订阅市场选择”当作真实交易时段；已改用逐市场 `is_market_trading()`。复现收盘后、周日和周一凌晨三项误清理后修复；仍保留盘中既有行为。本次上线只允许17:30–20:00香港时间，且须另行核对当日日线更新结束和分钟归档完成。

服务仅在启动时装配采集器，退出/重启会执行原有订阅清理和活跃度重筛，名单不保证不变。发布不执行前端构建、不重启OpenD、不启用真实交易。先备份版本及配置，再只添加四个 `RESEARCH_THEME_CAPTURE_*` 配置项；不得复制整个server.env覆盖线上.env。收盘重启通过 `bash scripts/restart_theme_capture.sh restart <完整提交SHA>`，脚本自身还有时窗、版本、工作区和健康检查，但不能代替归档完成核验。

启动日志 `Theme capture ready` 只确认独立证据库已打开；`Theme capture snapshot committed` 才表示已保存主题快照（仍为complete=false）。采集库由写线程独占锁定，运行中不要绕过SQLite锁读取或复制它；收盘后启动可能直到下一交易时段才有快照和信号。健康接口通过不代表主题采集完整、五股行情连续或策略有效。

用户随后明确确认现在部署，允许本日盘中维护。显式入口为 `bash scripts/restart_theme_capture.sh check-now <完整提交SHA> <获准的香港日期>`，检查通过后使用 `restart-now` 同参执行。该模式只在给定日期等于香港当日时生效，并以只读、3秒查询预算核实HK/US按原清理日期计算的日K线记录均为0；存在记录则拒绝，不删除或自动备份后强行放行。它不修改默认收盘时窗，也不提供长期自动部署授权。重启仍会短暂中断行情/提醒并按现有规则重建订阅。

7项通过，覆盖关闭、临时启用、配置错误、启动失败、生产者停止异常、真实信号方法接入，以及退出末尾信号保存。验收发现并修复关闭顺序：先停行情生产者，再排空采集器；退出时线程和模拟任务均已结束。此结果更新上一节的启动/停止待验收项，但不解除线上采集或策略门禁。
