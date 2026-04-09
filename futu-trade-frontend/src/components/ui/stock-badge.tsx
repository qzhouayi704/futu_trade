import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

interface StockBadgeProps {
  type: "up" | "down" | "neutral"
  children: React.ReactNode
  className?: string
}

export function StockBadge({ type, children, className }: StockBadgeProps) {
  return (
    <Badge
      className={cn(
        type === "up" && "bg-up text-white hover:bg-up/90",
        type === "down" && "bg-down text-white hover:bg-down/90",
        type === "neutral" && "bg-gray-500 text-white hover:bg-gray-500/90",
        className
      )}
    >
      {children}
    </Badge>
  )
}
