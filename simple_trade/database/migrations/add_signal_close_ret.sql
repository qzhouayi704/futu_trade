-- signal_performance 扩展：新增"持有到收盘的已实现收益"列（诚实记分牌）
-- day{1,3,5}_close_ret: 信号后第 N 天收盘相对 signal_price 的收益%（盘中每次报价覆盖，
--   当日最后一笔≈收盘，自然收敛为收盘收益）。区别于 day{1,3,5}_max_rise（摸高率）。
-- 注：SQLite 不支持 ADD COLUMN IF NOT EXISTS；重复执行会报 "duplicate column name"，
--   配套的 run_signal_close_ret_migration.py 会容错跳过已存在的列。

ALTER TABLE signal_performance ADD COLUMN day1_close_ret REAL;
ALTER TABLE signal_performance ADD COLUMN day3_close_ret REAL;
ALTER TABLE signal_performance ADD COLUMN day5_close_ret REAL;
