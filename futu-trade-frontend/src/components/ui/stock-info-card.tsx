import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { StockBadge } from "@/components/ui/stock-badge"
import { cn } from "@/lib/utils"

interface StockInfoCardProps {
  code: string
  name: string
  price: number
  change: number
  changePercent: number
  className?: string
}

export function StockInfoCard({
  code,
  name,
  price,
  change,
  changePercent,
  className
}: StockInfoCardProps) {
  const type = change > 0 ? "up" : change < 0 ? "down" : "neutral"

  return (
    <Card className={cn("hover:shadow-lg transition-shadow", className)}>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center justify-between text-base">
          <div className="flex flex-col gap-1">
            <span className="font-semibold">{name}</span>
            <span className="text-sm text-muted-foreground font-normal">{code}</span>
          </div>
          <StockBadge type={type}>
            {changePercent > 0 ? "+" : ""}{changePercent.toFixed(2)}%
          </StockBadge>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex items-baseline gap-2">
          <div className="text-2xl font-bold">{price.toFixed(2)}</div>
          <div className={cn(
            "text-sm font-medium",
            type === "up" && "text-up",
            type === "down" && "text-down",
            type === "neutral" && "text-gray-500"
          )}>
            {change > 0 ? "+" : ""}{change.toFixed(2)}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
