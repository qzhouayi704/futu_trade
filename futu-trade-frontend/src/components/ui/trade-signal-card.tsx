import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { cn, formatTime } from "@/lib/utils"
import { ArrowUpIcon, ArrowDownIcon } from "lucide-react"

interface TradeSignalCardProps {
  id: number
  stockCode: string
  stockName: string
  signalType: "buy" | "sell"
  signalPrice: number
  targetPrice?: number
  stopLossPrice?: number
  strategyName: string
  conditionText: string
  isExecuted: boolean
  executedTime?: string
  createdAt: string
  onExecute?: (id: number) => void
  className?: string
}

export function TradeSignalCard({
  id,
  stockCode,
  stockName,
  signalType,
  signalPrice,
  targetPrice,
  stopLossPrice,
  strategyName,
  conditionText,
  isExecuted,
  executedTime,
  createdAt,
  onExecute,
  className
}: TradeSignalCardProps) {
  const isBuy = signalType === "buy"

  return (
    <Card className={cn("hover:shadow-lg transition-shadow", className)}>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center justify-between text-base">
          <div className="flex items-center gap-2">
            <div
              className={cn(
                "flex items-center justify-center w-8 h-8 rounded-full",
                isBuy ? "bg-up/10" : "bg-down/10"
              )}
            >
              {isBuy ? (
                <ArrowUpIcon className="w-4 h-4 text-up" />
              ) : (
                <ArrowDownIcon className="w-4 h-4 text-down" />
              )}
            </div>
            <div className="flex flex-col">
              <span className="font-semibold">{stockName}</span>
              <span className="text-sm text-muted-foreground font-normal">
                {stockCode}
              </span>
            </div>
          </div>
          <Badge variant={isExecuted ? "secondary" : "default"}>
            {isExecuted ? "已执行" : "待执行"}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* 策略信息 */}
        <div className="flex items-center gap-2 text-sm">
          <Badge variant="secondary">{strategyName}</Badge>
          <span className="text-muted-foreground text-xs">{conditionText}</span>
        </div>

        {/* 价格信息 */}
        <div className="grid grid-cols-3 gap-2 text-sm">
          <div>
            <div className="text-muted-foreground">信号价</div>
            <div className="font-semibold text-base">
              {signalPrice.toFixed(2)}
            </div>
          </div>
          {targetPrice && (
            <div>
              <div className="text-muted-foreground">目标价</div>
              <div className="font-semibold text-base text-up">
                {targetPrice.toFixed(2)}
              </div>
            </div>
          )}
          {stopLossPrice && (
            <div>
              <div className="text-muted-foreground">止损价</div>
              <div className="font-semibold text-base text-down">
                {stopLossPrice.toFixed(2)}
              </div>
            </div>
          )}
        </div>

        {/* 时间信息 */}
        <div className="pt-2 border-t space-y-1 text-xs text-muted-foreground">
          <div className="flex justify-between">
            <span>创建时间</span>
            <span>{formatTime(createdAt)}</span>
          </div>
          {isExecuted && executedTime && (
            <div className="flex justify-between">
              <span>执行时间</span>
              <span>{formatTime(executedTime)}</span>
            </div>
          )}
        </div>

        {/* 操作按钮 */}
        {!isExecuted && onExecute && (
          <Button
            className="w-full"
            variant={isBuy ? "default" : "destructive"}
            onClick={() => onExecute(id)}
          >
            {isBuy ? "执行买入" : "执行卖出"}
          </Button>
        )}
      </CardContent>
    </Card>
  )
}
