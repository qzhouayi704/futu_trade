-- 止盈执行记录表扩展：添加 deal_id 和 order_id 字段
-- deal_id: 关联具体的成交记录ID
-- order_id: 报单成功后记录的 Futu 订单ID，用于后续查询成交状态

ALTER TABLE take_profit_executions ADD COLUMN deal_id TEXT;
ALTER TABLE take_profit_executions ADD COLUMN order_id TEXT;
CREATE INDEX IF NOT EXISTS idx_tp_exec_deal ON take_profit_executions(deal_id);
