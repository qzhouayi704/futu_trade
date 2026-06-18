import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils/index"

// 语义小标签：买/卖/观望/涨/跌/中性 — 令牌驱动，暗色自适应
// 替代散落各处的硬编码彩色 <span>（bg-emerald-500/bg-red-100 等）
const chipVariants = cva(
  "inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-bold leading-none whitespace-nowrap",
  {
    variants: {
      variant: {
        buy: "bg-profit text-profit",
        risk: "bg-loss text-loss",
        watch: "bg-amber-500/15 text-amber-600 dark:text-amber-400",
        up: "text-profit",
        down: "text-loss",
        neutral: "bg-muted text-muted-foreground",
        accent: "bg-primary/15 text-primary",
      },
    },
    defaultVariants: {
      variant: "neutral",
    },
  }
)

export interface ChipProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof chipVariants> {}

function Chip({ className, variant, ...props }: ChipProps) {
  return <span className={cn(chipVariants({ variant }), className)} {...props} />
}

export { Chip, chipVariants }
