// 快速下单弹窗 — 信号旁一键下单
// 点击打开 Popover → 自动 Pre-check → 填入数量 → 确认下单

"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { tradeApi } from "@/lib/api";
import { useToast } from "@/components/common/Toast";

// ── 类型 ──────────────────────────────────────

interface PreCheckResult {
  stock_code: string;
  stock_name: string;
  verdict: "GO" | "CAUTION" | "STOP" | "UNKNOWN";
  verdict_reason: string;
  score: number;
  checks: { name: string; status: string; detail: string }[];
  warnings: string[];
  holding_strategy?: {
    type: string;
    label: string;
    icon: string;
    color: string;
    reason: string;
  };
}

interface QuickOrderPopoverProps {
  stockCode: string;
  stockName: string;
  price?: number;        // 信号价格（触发时）
  direction: "buy" | "sell";
}

// ── 快捷数量选项 ──────────────────────────────

const QTY_OPTIONS = [100, 200, 500, 1000, 2000];

// ── 组件 ──────────────────────────────────────

export function QuickOrderPopover({ stockCode, stockName, price, direction }: QuickOrderPopoverProps) {
  const { showToast } = useToast();
  const [isOpen, setIsOpen] = useState(false);
  const [quantity, setQuantity] = useState(100);
  const [useMarketPrice, setUseMarketPrice] = useState(true);
  const [limitPrice, setLimitPrice] = useState<number | null>(price || null);
  const [preCheck, setPreCheck] = useState<PreCheckResult | null>(null);
  const [checking, setChecking] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [step, setStep] = useState<"form" | "confirm">("form");
  const popoverRef = useRef<HTMLDivElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);

  // ── 点击外部关闭 ────────────────────────────

  useEffect(() => {
    if (!isOpen) return;
    const handler = (e: MouseEvent) => {
      if (
        popoverRef.current &&
        !popoverRef.current.contains(e.target as Node) &&
        btnRef.current &&
        !btnRef.current.contains(e.target as Node)
      ) {
        setIsOpen(false);
        setStep("form");
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [isOpen]);

  // ── 打开时自动 Pre-check ────────────────────

  const runPreCheck = useCallback(async () => {
    setChecking(true);
    setPreCheck(null);
    try {
      const res = await fetch(`/api/pre-trade-check/${encodeURIComponent(stockCode)}`);
      const json = await res.json();
      if (json.success && json.data) {
        setPreCheck(json.data);
        // 如果 pre-check 返回了股票名，可以用；价格用信号价
      }
    } catch (err) {
      console.error("Pre-check failed:", err);
    } finally {
      setChecking(false);
    }
  }, [stockCode]);

  const handleOpen = (e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    if (isOpen) {
      setIsOpen(false);
      setStep("form");
      return;
    }
    setIsOpen(true);
    setStep("form");
    setQuantity(100);
    setUseMarketPrice(true);
    setLimitPrice(price || null);
    runPreCheck();
  };

  // ── 执行下单 ────────────────────────────────

  const handleExecute = async () => {
    setExecuting(true);
    try {
      const response = await tradeApi.executeTrade({
        stock_code: stockCode,
        trade_type: direction,
        quantity,
        price: useMarketPrice ? undefined : (limitPrice || undefined),
      });
      if (response.success) {
        showToast("success", "下单成功", `${stockName} ${direction === "buy" ? "买入" : "卖出"} ${quantity}股 已提交`);
        setIsOpen(false);
        setStep("form");
      } else {
        throw new Error(response.message || "下单失败");
      }
    } catch (err: any) {
      showToast("error", "下单失败", err.message || "请检查富途客户端连接");
    } finally {
      setExecuting(false);
    }
  };

  // ── 判定颜色 ────────────────────────────────

  const verdictConfig = {
    GO: { bg: "bg-emerald-50", border: "border-emerald-300", text: "text-emerald-700", icon: "✅", label: "可以买入" },
    CAUTION: { bg: "bg-amber-50", border: "border-amber-300", text: "text-amber-700", icon: "⚠️", label: "谨慎操作" },
    STOP: { bg: "bg-red-50", border: "border-red-300", text: "text-red-700", icon: "🚫", label: "不建议买入" },
    UNKNOWN: { bg: "bg-gray-50", border: "border-gray-300", text: "text-gray-700", icon: "❓", label: "未知" },
  };

  const isBuy = direction === "buy";
  const displayName = preCheck?.stock_name || stockName;

  return (
    <div className="relative inline-block">
      {/* 触发按钮 */}
      <button
        ref={btnRef}
        onClick={handleOpen}
        className={`text-[9px] px-1.5 py-0.5 rounded font-medium transition-all ${
          isOpen
            ? "bg-primary text-primary-foreground shadow-sm"
            : isBuy
              ? "bg-red-100/80 text-red-700 dark:bg-red-900/40 dark:text-red-300 hover:bg-red-200 dark:hover:bg-red-800/50"
              : "bg-green-100/80 text-green-700 dark:bg-green-900/40 dark:text-green-300 hover:bg-green-200 dark:hover:bg-green-800/50"
        }`}
      >
        ⚡{isBuy ? "买入" : "卖出"}
      </button>

      {/* Popover */}
      {isOpen && (
        <div
          ref={popoverRef}
          className="absolute right-0 top-full mt-1 z-50 w-[280px] rounded-xl border border-border bg-card shadow-xl animate-in fade-in slide-in-from-top-2 duration-200"
          onClick={(e) => e.stopPropagation()}
        >
          {/* 标题 */}
          <div className={`px-3 py-2 rounded-t-xl border-b ${isBuy ? "bg-red-50/80 dark:bg-red-950/30" : "bg-green-50/80 dark:bg-green-950/30"} border-border`}>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <span className={`text-xs font-bold ${isBuy ? "text-red-600" : "text-green-600"}`}>
                  {isBuy ? "📈 快速买入" : "📉 快速卖出"}
                </span>
              </div>
              <button
                onClick={() => { setIsOpen(false); setStep("form"); }}
                className="text-muted-foreground hover:text-foreground text-sm leading-none px-1"
              >
                ✕
              </button>
            </div>
            <div className="flex items-center gap-1.5 mt-1">
              <span className="text-xs font-bold text-foreground">{displayName}</span>
              <span className="text-[10px] text-muted-foreground">{stockCode}</span>
              {price && (
                <span className="text-[10px] text-muted-foreground ml-auto">
                  信号价 {price.toFixed(3)}
                </span>
              )}
            </div>
          </div>

          {step === "form" ? (
            <div className="p-3 space-y-3">
              {/* Pre-check 结果 */}
              {checking ? (
                <div className="flex items-center gap-2 text-xs text-muted-foreground py-1">
                  <div className="w-3.5 h-3.5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                  交易检查中...
                </div>
              ) : preCheck ? (
                <div className={`rounded-lg p-2 border ${verdictConfig[preCheck.verdict].bg} ${verdictConfig[preCheck.verdict].border}`}>
                  <div className="flex items-center justify-between">
                    <span className={`text-[11px] font-bold ${verdictConfig[preCheck.verdict].text}`}>
                      {verdictConfig[preCheck.verdict].icon} {preCheck.verdict} · 评分 {preCheck.score}
                    </span>
                    <span className={`text-[9px] px-1.5 py-0.5 rounded-full font-medium ${
                      preCheck.verdict === "GO" ? "bg-emerald-200 text-emerald-800"
                        : preCheck.verdict === "CAUTION" ? "bg-amber-200 text-amber-800"
                        : "bg-red-200 text-red-800"
                    }`}>
                      {verdictConfig[preCheck.verdict].label}
                    </span>
                  </div>
                  <p className={`text-[10px] mt-1 ${verdictConfig[preCheck.verdict].text} opacity-80`}>
                    {preCheck.verdict_reason}
                  </p>
                  {/* 关键检查项（最多显示3条） */}
                  {preCheck.checks?.length > 0 && (
                    <div className="mt-1.5 space-y-0.5">
                      {preCheck.checks.slice(0, 3).map((c, i) => (
                        <div key={i} className="flex items-center justify-between text-[10px]">
                          <span className="text-gray-600 dark:text-gray-400">
                            {c.status === "GOOD" ? "✅" : c.status === "DANGER" ? "❌" : c.status === "WARNING" ? "⚠️" : "⚪"}{" "}
                            {c.name}
                          </span>
                          <span className="text-gray-500 dark:text-gray-400 truncate ml-2 max-w-[140px]" title={c.detail}>
                            {c.detail}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ) : null}

              {/* 数量选择 */}
              <div>
                <label className="text-[10px] font-medium text-muted-foreground mb-1 block">交易数量（股）</label>
                <div className="flex items-center gap-1 flex-wrap">
                  {QTY_OPTIONS.map((q) => (
                    <button
                      key={q}
                      onClick={() => setQuantity(q)}
                      className={`text-[10px] px-2 py-1 rounded-md font-medium transition-all ${
                        quantity === q
                          ? "bg-primary text-primary-foreground shadow-sm"
                          : "bg-muted/60 text-muted-foreground hover:bg-muted hover:text-foreground"
                      }`}
                    >
                      {q}
                    </button>
                  ))}
                  <input
                    type="number"
                    value={quantity}
                    onChange={(e) => setQuantity(Math.max(100, parseInt(e.target.value) || 100))}
                    min={100}
                    step={100}
                    className="w-16 text-[10px] px-2 py-1 rounded-md border border-border bg-background text-foreground text-center"
                  />
                </div>
              </div>

              {/* 价格选择 */}
              <div>
                <label className="text-[10px] font-medium text-muted-foreground mb-1 block">交易价格</label>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setUseMarketPrice(true)}
                    className={`text-[10px] px-2.5 py-1 rounded-md font-medium transition-all ${
                      useMarketPrice
                        ? "bg-primary text-primary-foreground shadow-sm"
                        : "bg-muted/60 text-muted-foreground hover:bg-muted"
                    }`}
                  >
                    市价
                  </button>
                  <button
                    onClick={() => { setUseMarketPrice(false); if (!limitPrice && price) setLimitPrice(price); }}
                    className={`text-[10px] px-2.5 py-1 rounded-md font-medium transition-all ${
                      !useMarketPrice
                        ? "bg-primary text-primary-foreground shadow-sm"
                        : "bg-muted/60 text-muted-foreground hover:bg-muted"
                    }`}
                  >
                    限价
                  </button>
                  {!useMarketPrice && (
                    <input
                      type="number"
                      value={limitPrice || ""}
                      onChange={(e) => setLimitPrice(e.target.value ? parseFloat(e.target.value) : null)}
                      step={0.01}
                      placeholder="输入价格"
                      className="flex-1 text-[10px] px-2 py-1 rounded-md border border-border bg-background text-foreground"
                    />
                  )}
                </div>
              </div>

              {/* 预估金额 */}
              {price && (
                <div className="text-[10px] text-muted-foreground flex items-center justify-between px-1">
                  <span>预估金额</span>
                  <span className="font-bold text-foreground tabular-nums">
                    HK$ {((useMarketPrice ? price : (limitPrice || price)) * quantity).toLocaleString("en", { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
                  </span>
                </div>
              )}

              {/* 操作按钮 */}
              <button
                onClick={() => setStep("confirm")}
                disabled={quantity < 100}
                className={`w-full py-2 rounded-lg text-xs font-bold transition-all ${
                  isBuy
                    ? "bg-red-600 hover:bg-red-700 text-white disabled:bg-red-300"
                    : "bg-green-600 hover:bg-green-700 text-white disabled:bg-green-300"
                } disabled:cursor-not-allowed`}
              >
                {isBuy ? "确认买入" : "确认卖出"} {quantity}股
              </button>
            </div>
          ) : (
            /* 确认步骤 */
            <div className="p-3 space-y-3">
              <div className={`rounded-lg p-3 border ${
                preCheck?.verdict === "STOP"
                  ? "bg-red-50 border-red-200 dark:bg-red-950/20 dark:border-red-800/40"
                  : "bg-blue-50 border-blue-200 dark:bg-blue-950/20 dark:border-blue-800/40"
              }`}>
                <div className="text-xs font-bold text-foreground mb-2">
                  {preCheck?.verdict === "STOP" ? "⚠️ 系统建议不要买入，确定继续？" : "请确认交易信息"}
                </div>
                <div className="space-y-1 text-[11px]">
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">股票</span>
                    <span className="font-medium text-foreground">{displayName} ({stockCode})</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">方向</span>
                    <span className={`font-bold ${isBuy ? "text-red-600" : "text-green-600"}`}>
                      {isBuy ? "买入" : "卖出"}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">数量</span>
                    <span className="font-medium text-foreground">{quantity}股</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">价格</span>
                    <span className="font-medium text-foreground">
                      {useMarketPrice ? "市价" : `HK$ ${limitPrice?.toFixed(3) || "--"}`}
                    </span>
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <button
                  onClick={() => setStep("form")}
                  disabled={executing}
                  className="py-2 rounded-lg text-xs font-medium bg-muted text-muted-foreground hover:bg-muted/80 transition-all"
                >
                  返回修改
                </button>
                <button
                  onClick={handleExecute}
                  disabled={executing}
                  className={`py-2 rounded-lg text-xs font-bold text-white transition-all ${
                    executing ? "opacity-60 cursor-wait" : ""
                  } ${
                    preCheck?.verdict === "STOP"
                      ? "bg-red-600 hover:bg-red-700"
                      : isBuy
                        ? "bg-red-600 hover:bg-red-700"
                        : "bg-green-600 hover:bg-green-700"
                  }`}
                >
                  {executing ? (
                    <span className="flex items-center justify-center gap-1.5">
                      <span className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />
                      提交中
                    </span>
                  ) : preCheck?.verdict === "STOP" ? (
                    "⚠️ 强制执行"
                  ) : (
                    "🚀 确认提交"
                  )}
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
