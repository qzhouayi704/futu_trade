import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { StockBadge } from "@/components/ui/stock-badge"
import { cn } from "@/lib/utils"

interface Stock {
  code: string
  name: string
  price: number
  change: number
  changePercent: number
  volume?: number
  turnover?: number
}

interface StockTableProps {
  stocks: Stock[]
  onRowClick?: (stock: Stock) => void
  className?: string
}

export function StockTable({ stocks, onRowClick, className }: StockTableProps) {
  return (
    <div className={cn("rounded-md border", className)}>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>股票代码</TableHead>
            <TableHead>股票名称</TableHead>
            <TableHead className="text-right">最新价</TableHead>
            <TableHead className="text-right">涨跌额</TableHead>
            <TableHead className="text-right">涨跌幅</TableHead>
            {stocks[0]?.volume !== undefined && (
              <TableHead className="text-right">成交量</TableHead>
            )}
            {stocks[0]?.turnover !== undefined && (
              <TableHead className="text-right">成交额</TableHead>
            )}
          </TableRow>
        </TableHeader>
        <TableBody>
          {stocks.length === 0 ? (
            <TableRow>
              <TableCell
                colSpan={7}
                className="h-24 text-center text-muted-foreground"
              >
                暂无数据
              </TableCell>
            </TableRow>
          ) : (
            stocks.map((stock) => {
              const type = stock.change > 0 ? "up" : stock.change < 0 ? "down" : "neutral"
              return (
                <TableRow
                  key={stock.code}
                  className={cn(
                    onRowClick && "cursor-pointer hover:bg-muted/50"
                  )}
                  onClick={() => onRowClick?.(stock)}
                >
                  <TableCell className="font-medium">{stock.code}</TableCell>
                  <TableCell>{stock.name}</TableCell>
                  <TableCell className="text-right font-medium">
                    {stock.price.toFixed(2)}
                  </TableCell>
                  <TableCell
                    className={cn(
                      "text-right font-medium",
                      type === "up" && "text-up",
                      type === "down" && "text-down"
                    )}
                  >
                    {stock.change > 0 ? "+" : ""}
                    {stock.change.toFixed(2)}
                  </TableCell>
                  <TableCell className="text-right">
                    <StockBadge type={type}>
                      {stock.changePercent > 0 ? "+" : ""}
                      {stock.changePercent.toFixed(2)}%
                    </StockBadge>
                  </TableCell>
                  {stock.volume !== undefined && (
                    <TableCell className="text-right">
                      {(stock.volume / 10000).toFixed(2)}万
                    </TableCell>
                  )}
                  {stock.turnover !== undefined && (
                    <TableCell className="text-right">
                      {(stock.turnover / 10000).toFixed(2)}万
                    </TableCell>
                  )}
                </TableRow>
              )
            })
          )}
        </TableBody>
      </Table>
    </div>
  )
}
