// 持仓做T助手 · 控制台 + 当日做T总览
// 高抛低吸两腿状态机：高位+主力净流出→建议减一档；回落+资金回流→建议买回摊低成本。
// 分阶段：先告警(只推建议·不下单)→ 再半自动(一键确认走 /api/trading/execute)。

"use client";

import { useState } from "react";
import Link from "next/link";
import { Card } from "@/components/common";
import { useTTradeStatus } from "@/app/hooks/useTTrade";
import { tTradeApi, type TLeg } from "@/lib/api/t-trade";

// 状态 → 中文标签 + 配色
const STATE_META: Record<string, { label: string; cls: string }> = {
  IDLE: { label: "空闲", cls: "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300" },
  SELL_PENDING: { label: "待确认高抛", cls: "bg-amber-100 text-amber-700 dark:bg-amber-500/20 dark:text-amber-400" },
  SOLD_WAITING_BUYBACK: { label: "高抛·待回补", cls: "bg-orange-100 text-orange-700 dark:bg-orange-500/20 dark:text-orange-400" },
  BUY_PENDING: { label: "待确认买回", cls: "bg-sky-100 text-sky-700 dark:bg-sky-500/20 dark:text-sky-400" },
  COMPLETED: { label: "做T完成", cls: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-400" },
  EXPIRED: { label: "已失效", cls: "bg-gray-100 text-gray-400 dark:bg-gray-800 dark:text-gray-500" },
};

// 钱的盈亏：红涨绿跌（与持仓面板一致）
function pnlClass(v: number | null | undefined): string {
  if (v == null) return "text-muted-foreground";
  return v >= 0 ? "text-red-500" : "text-green-500";
}
function fmtPnl(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(0)}`;
}
function fmtPrice(v: number | null | undefined): string {
  return v != null ? v.toFixed(3) : "—";
}

export default function TTradePage() {
  const { data: status, isLoading, refetch } = useTTradeStatus();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string>("");

  const enabled = !!status?.enabled;
  const mode = status?.mode ?? "alert";
  const legs: TLeg[] = status?.legs ?? [];
  const cfg = status?.config ?? {};

  const flash = (m: string) => {
    setMsg(m);
    window.setTimeout(() => setMsg(""), 4000);
  };

  const toggleEnabled = async () => {
    setBusy(true);
    try {
      const r = await tTradeApi.setConfig({ enabled: !enabled });
      flash(r?.message || (enabled ? "已关闭做T助手" : "已开启做T助手(告警)"));
      await refetch();
    } catch (e) {
      flash("操作失败：" + String(e));
    } finally {
      setBusy(false);
    }
  };

  const cancelLeg = async (legId: number) => {
    setBusy(true);
    try {
      const r = await tTradeApi.cancel(legId);
      flash(r?.message || "已取消");
      await refetch();
    } catch (e) {
      flash("取消失败：" + String(e));
    } finally {
      setBusy(false);
    }
  };

  const confirmLeg = async (legId: number) => {
    setBusy(true);
    try {
      const r = await tTradeApi.confirm(legId);
      flash(r?.message || "已确认");
      await refetch();
    } catch (e) {
      flash("确认失败：" + String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="max-w-5xl mx-auto p-4 sm:p-6">
      {/* 标题 */}
      <div className="flex items-center justify-between flex-wrap gap-2 mb-4">
        <h1 className="text-lg font-bold flex items-center gap-2">
          <span>🅣</span> 持仓做T助手
          <span className="text-[10px] px-1.5 py-px rounded bg-amber-500/15 text-amber-600 dark:text-amber-400 font-bold">
            {mode === "alert" ? "告警阶段·不下单" : mode}
          </span>
        </h1>
        <Link href="/" className="text-xs text-sky-600 dark:text-sky-400 hover:underline">
          ← 返回驾驶舱
        </Link>
      </div>

      {msg && (
        <div className="mb-3 text-xs px-3 py-2 rounded-lg bg-sky-50 text-sky-700 dark:bg-sky-950/40 dark:text-sky-300 border border-sky-200/50 dark:border-sky-800/40">
          {msg}
        </div>
      )}

      {/* 控制台 */}
      <Card className="mb-4">
        <div className="p-4">
          <div className="flex items-center justify-between flex-wrap gap-3">
            <div className="flex items-center gap-3">
              <button
                onClick={toggleEnabled}
                disabled={busy}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                  enabled ? "bg-emerald-500" : "bg-gray-300 dark:bg-gray-600"
                } ${busy ? "opacity-50" : ""}`}
                title="做T助手总开关"
              >
                <span
                  className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                    enabled ? "translate-x-6" : "translate-x-1"
                  }`}
                />
              </button>
              <div>
                <div className="text-sm font-semibold text-foreground">
                  做T助手 {enabled ? "已开启" : "已关闭"}
                </div>
                <div className="text-[11px] text-muted-foreground">
                  {enabled
                    ? "盘中对波动大+流动性好的持仓股自动判读高抛/买回时机并推企微建议"
                    : "默认关闭。开启后仅推送建议、用现价虚拟记账验证，绝不自动下单"}
                </div>
              </div>
            </div>

            {/* 模式（半自动为 Phase 2） */}
            <div className="flex items-center gap-1 text-xs">
              <span className={`px-2.5 py-1 rounded-md font-medium ${
                mode === "alert" ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"
              }`}>
                告警
              </span>
              <span className="px-2.5 py-1 rounded-md font-medium bg-muted text-muted-foreground/60 cursor-not-allowed"
                title="半自动一键下单将于 Phase 2 开放">
                半自动 (即将开放)
              </span>
            </div>
          </div>

          {/* 护栏参数（只读展示） */}
          <div className="mt-3 pt-3 border-t border-border/40 grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-1.5 text-[11px]">
            <GuardItem label="单次减仓" value={cfg.trim_fraction != null ? `${(cfg.trim_fraction * 100).toFixed(0)}% 仓` : "—"} />
            <GuardItem label="底仓保留" value={cfg.min_core_fraction != null ? `≥${(cfg.min_core_fraction * 100).toFixed(0)}%` : "—"} />
            <GuardItem label="每股每日上限" value={cfg.max_per_day != null ? `${cfg.max_per_day} 次` : "—"} />
            <GuardItem label="买回利润间隔" value={cfg.min_profit_gap_pct != null ? `≥${cfg.min_profit_gap_pct}%` : "—"} />
            <GuardItem label="武装买回回落" value={cfg.buyback_drawdown_pct != null ? `≥${cfg.buyback_drawdown_pct}%` : "—"} />
            <GuardItem label="当日亏损熔断" value={cfg.daily_loss_kill_hkd != null ? `${cfg.daily_loss_kill_hkd} HKD` : "—"} />
          </div>
        </div>
      </Card>

      {/* 当日总览 */}
      <div className="flex items-center justify-between flex-wrap gap-2 mb-2 text-sm">
        <h2 className="font-semibold text-foreground">
          当日做T {status?.trade_date ? <span className="text-xs text-muted-foreground">({status.trade_date})</span> : null}
        </h2>
        <span className="text-xs text-muted-foreground">
          共 <b>{legs.length}</b> 笔 · 已实现{" "}
          <b className={pnlClass(status?.realized_pnl_today)}>{fmtPnl(status?.realized_pnl_today)}</b> HKD
        </span>
      </div>

      {isLoading ? (
        <div className="text-center text-muted-foreground py-10 text-sm">加载中...</div>
      ) : !status ? (
        <div className="text-center text-muted-foreground py-10 text-sm leading-relaxed">
          做T助手暂不可用（后端未启用或未部署）。
          <br />
          <span className="text-xs text-muted-foreground/60">部署上线后此处会显示当日做T腿与触发状态。</span>
        </div>
      ) : legs.length === 0 ? (
        <div className="text-center text-muted-foreground py-10 text-sm leading-relaxed">
          {enabled ? "今日暂无做T信号" : "做T助手当前关闭"}
          <br />
          <span className="text-xs text-muted-foreground/60">
            {enabled
              ? "盘中出现「持仓股逼近日高 + 主力净流出」会建议高抛，回落+资金回流会建议买回。"
              : "打开上方开关即开始告警判读（不下单）。"}
          </span>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-xs">
            <thead className="bg-muted/50 text-muted-foreground">
              <tr className="[&>th]:px-2 [&>th]:py-2 [&>th]:text-left [&>th]:font-medium whitespace-nowrap">
                <th>股票</th>
                <th>状态</th>
                <th className="text-right">卖出价</th>
                <th className="text-right">买回/目标</th>
                <th className="text-right">股数</th>
                <th className="text-right">实现盈亏</th>
                <th>原因</th>
                <th></th>
              </tr>
            </thead>
            <tbody className="[&>tr]:border-t [&>tr]:border-border">
              {legs.map((leg) => {
                const meta = STATE_META[leg.state] || STATE_META.IDLE;
                const buyShown = leg.bought_price ?? leg.target_buyback_price;
                const isPending = leg.state === "SELL_PENDING" || leg.state === "BUY_PENDING";
                const reason = leg.buy_reason || leg.sell_reason || "";
                return (
                  <tr key={leg.id} className="[&>td]:px-2 [&>td]:py-1.5 align-top">
                    <td className="font-medium whitespace-nowrap">
                      {leg.stock_name || leg.stock_code}
                      <div className="text-[10px] text-muted-foreground">{leg.stock_code}</div>
                    </td>
                    <td className="whitespace-nowrap">
                      <span className={`text-[10px] px-1.5 py-px rounded-full font-medium ${meta.cls}`}>
                        {meta.label}
                      </span>
                    </td>
                    <td className="text-right tabular-nums whitespace-nowrap">
                      {fmtPrice(leg.sold_price)}
                      {leg.sold_time ? <div className="text-[10px] text-muted-foreground">{leg.sold_time}</div> : null}
                    </td>
                    <td className="text-right tabular-nums whitespace-nowrap">
                      {fmtPrice(buyShown)}
                      {leg.bought_time ? <div className="text-[10px] text-muted-foreground">{leg.bought_time}</div> : null}
                    </td>
                    <td className="text-right tabular-nums">{leg.sold_qty || "—"}</td>
                    <td className={`text-right tabular-nums ${pnlClass(leg.realized_pnl)}`}>
                      {leg.realized_pnl != null ? fmtPnl(leg.realized_pnl) : "—"}
                    </td>
                    <td className="text-muted-foreground max-w-[240px] truncate" title={reason}>
                      {reason}
                    </td>
                    <td className="whitespace-nowrap text-right">
                      {isPending && (
                        <div className="flex gap-1 justify-end">
                          <button
                            onClick={() => confirmLeg(leg.id)}
                            disabled={busy}
                            className="text-[10px] px-2 py-0.5 rounded bg-primary text-primary-foreground font-medium disabled:opacity-50"
                          >
                            确认
                          </button>
                          <button
                            onClick={() => cancelLeg(leg.id)}
                            disabled={busy}
                            className="text-[10px] px-2 py-0.5 rounded bg-muted text-muted-foreground font-medium disabled:opacity-50"
                          >
                            取消
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-[11px] text-muted-foreground mt-3 leading-relaxed">
        🅣 做T助手对<b>持仓股</b>做正T（先卖后买、摊低成本）：「逼近日高/涨≥2% + 主力净流出」建议高抛一档，
        「回落≥2% + 资金回流 + 动量企稳」且比卖出价低≥1.5% 建议买回。<b>当前为告警阶段</b>，
        只推企微建议并用现价虚拟记账验证准不准，<b>不下任何真单</b>；半自动一键下单将于下一阶段开放。
      </p>
    </div>
  );
}

function GuardItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium text-foreground tabular-nums">{value}</span>
    </div>
  );
}
