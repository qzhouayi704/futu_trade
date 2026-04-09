import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { StockBadge } from "@/components/ui/stock-badge"
import { Progress } from "@/components/ui/progress"
import { cn } from "@/lib/utils"

interface PositionCardProps {
  code: string
  name: string
  quantity: number
  availableQuantity: number
  costPrice: number
  currentPrice: number
  marketValue: number
  profitLoss: number
  profitLossPercent: number
  todayProfitLoss?: number
  className?: string
}

export function PositionCard({
  code,
  name,
  quantity,
  availableQuantity,
  costPrice,
  currentPrice,
  marketValue,
  profitLoss,
  profitLossPercent,
  todayProfitLoss,
  className
}: PositionCardProps) {
  const type = profitLoss > 0 ? "up" : profitLoss < 0 ? "down" : "neutral"
  const positionRatio = (availableQuantity / quantity) * 100

  return (
    <Card className={cn("hover:shadow-lg transition-shadow", className)}>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center justify-between text-base">
          <div className="flex flex-col gap-1">
            <span className="font-semibold">{name}</span>
            <span className="text-sm text-muted-foreground font-normal">{code}</span>
          </div>
          <StockBadge type={type}>
            {profitLossPercent > 0 ? "+" : ""}
            {profitLossPercent.toFixed(2)}%
          </StockBadge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* 价格信息 */}
        <div className="grid grid-cols-2 gap-2 text-sm">
          <div>
            <div className="text-muted-foreground">当前价</div>
            <div className="font-semibold">{currentPrice.toFixed(2)}</div>
          </div>
          <div>
            <div className="text-muted-foreground">成本价</div>
            <div className="font-semibold">{costPrice.toFixed(2)}</div>
          </div>
        </div>

        {/* 持仓信息 */}
        <div className="grid grid-cols-2 gap-2 text-sm">
          <div>
            <div className="text-muted-foreground">持仓数量</div>
            <div className="font-semibold">{quantity}</div>
          </div>
          <div>
            <div className="text-muted-foreground">可用数量</div>
            <div className="font-semibold">{availableQuantity}</div>
          </div>
        </div>

        {/* 可用比例 */}
        <div className="space-y-1">
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>可用比例</span>
            <span>{positionRatio.toFixed(1)}%</span>
          </div>
          <Progress value={positionRatio} className="h-1" />
        </div>

        {/* 盈亏信息 */}
        <div className="pt-2 border-t space-y-2">
          <div className="flex justify-between items-center">
            <span className="text-sm text-muted-foreground">市值</span>
            <span className="font-semibold">¥{marketValue.toFixed(2)}</span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-sm text-muted-foreground">总盈亏</span>
            <span
              className={cn(
                "font-semibold",
                type === "up" && "text-up",
                type === "down" && "text-down"
              )}
            >
              {profitLoss > 0 ? "+" : ""}¥{profitLoss.toFixed(2)}
            </span>
          </div>
          {todayProfitLoss !== undefined && (
            <div className="flex justify-between items-center">
              <span className="text-sm text-muted-foreground">今日盈亏</span>
              <span
                className={cn(
                  "font-semibold",
                  todayProfitLoss > 0 && "text-up",
                  todayProfitLoss < 0 && "text-down"
                )}
              >
                {todayProfitLoss > 0 ? "+" : ""}¥{todayProfitLoss.toFixed(2)}
              </span>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
