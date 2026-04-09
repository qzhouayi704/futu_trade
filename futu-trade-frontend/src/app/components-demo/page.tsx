"use client"

import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Checkbox } from "@/components/ui/checkbox"
import { Badge } from "@/components/ui/badge"
import { StockBadge } from "@/components/ui/stock-badge"
import { StockInfoCard } from "@/components/ui/stock-info-card"
import { StockTable } from "@/components/ui/stock-table"
import { PositionCard } from "@/components/ui/position-card"
import { TradeSignalCard } from "@/components/ui/trade-signal-card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Progress } from "@/components/ui/progress"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { Separator } from "@/components/ui/separator"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { AlertCircle, InfoIcon } from "lucide-react"

export default function ComponentsDemo() {
  return (
    <div className="container mx-auto p-8 space-y-8">
      <div className="space-y-2">
        <h1 className="text-3xl font-bold">shadcn/ui 组件示例</h1>
        <p className="text-muted-foreground">
          展示已集成的 shadcn/ui 组件和股票特定组件
        </p>
      </div>

      {/* 按钮示例 */}
      <Card>
        <CardHeader>
          <CardTitle>Button 按钮</CardTitle>
          <CardDescription>不同变体和尺寸的按钮</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-4">
          <Button>默认按钮</Button>
          <Button variant="secondary">次要按钮</Button>
          <Button variant="destructive">危险按钮</Button>
          <Button variant="secondary">轮廓按钮</Button>
          <Button variant="ghost">幽灵按钮</Button>
          <Button variant="link">链接按钮</Button>
          <Button size="sm">小按钮</Button>
          <Button size="lg">大按钮</Button>
        </CardContent>
      </Card>

      {/* 表单组件示例 */}
      <Card>
        <CardHeader>
          <CardTitle>表单组件</CardTitle>
          <CardDescription>Input, Label, Select, Checkbox</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="name">姓名</Label>
            <Input id="name" placeholder="请输入姓名" />
          </div>

          <div className="space-y-2">
            <Label htmlFor="stock">选择股票</Label>
            <Select>
              <SelectTrigger id="stock">
                <SelectValue placeholder="选择一只股票" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="00700">腾讯控股 (00700)</SelectItem>
                <SelectItem value="09988">阿里巴巴 (09988)</SelectItem>
                <SelectItem value="03690">美团 (03690)</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="flex items-center space-x-2">
            <Checkbox id="terms" />
            <Label htmlFor="terms">同意交易条款</Label>
          </div>
        </CardContent>
      </Card>

      {/* Badge 示例 */}
      <Card>
        <CardHeader>
          <CardTitle>Badge 徽章</CardTitle>
          <CardDescription>标准徽章和股票特定徽章</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-4">
          <Badge>默认</Badge>
          <Badge variant="secondary">次要</Badge>
          <Badge variant="destructive">危险</Badge>
          <Badge variant="secondary">轮廓</Badge>
          <StockBadge type="up">+5.23%</StockBadge>
          <StockBadge type="down">-2.15%</StockBadge>
          <StockBadge type="neutral">0.00%</StockBadge>
        </CardContent>
      </Card>

      {/* 股票信息卡片示例 */}
      <div className="space-y-4">
        <h2 className="text-2xl font-bold">股票信息卡片</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          <StockInfoCard
            code="00700.HK"
            name="腾讯控股"
            price={385.60}
            change={12.40}
            changePercent={3.32}
          />
          <StockInfoCard
            code="09988.HK"
            name="阿里巴巴"
            price={78.50}
            change={-2.30}
            changePercent={-2.85}
          />
          <StockInfoCard
            code="03690.HK"
            name="美团"
            price={142.80}
            change={0.00}
            changePercent={0.00}
          />
        </div>
      </div>

      {/* 卡片组合示例 */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card>
          <CardHeader>
            <CardTitle>持仓概览</CardTitle>
            <CardDescription>当前持仓统计</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              <div className="flex justify-between">
                <span className="text-muted-foreground">总市值</span>
                <span className="font-semibold">¥125,680.00</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">总盈亏</span>
                <span className="font-semibold text-up">+¥8,520.00</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">盈亏比例</span>
                <StockBadge type="up">+7.28%</StockBadge>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>今日交易</CardTitle>
            <CardDescription>交易统计</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              <div className="flex justify-between">
                <span className="text-muted-foreground">买入</span>
                <span className="font-semibold text-up">3 笔</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">卖出</span>
                <span className="font-semibold text-down">2 笔</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">成交额</span>
                <span className="font-semibold">¥45,200.00</span>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <Separator />

      {/* 股票表格示例 */}
      <div className="space-y-4">
        <h2 className="text-2xl font-bold">股票表格</h2>
        <StockTable
          stocks={[
            { code: "00700.HK", name: "腾讯控股", price: 385.60, change: 12.40, changePercent: 3.32, volume: 12500000, turnover: 4820000000 },
            { code: "09988.HK", name: "阿里巴巴", price: 78.50, change: -2.30, changePercent: -2.85, volume: 8900000, turnover: 698650000 },
            { code: "03690.HK", name: "美团", price: 142.80, change: 0.00, changePercent: 0.00, volume: 5600000, turnover: 799680000 },
          ]}
          onRowClick={(stock) => console.log("点击股票:", stock)}
        />
      </div>

      <Separator />

      {/* 持仓卡片示例 */}
      <div className="space-y-4">
        <h2 className="text-2xl font-bold">持仓卡片</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          <PositionCard
            code="00700.HK"
            name="腾讯控股"
            quantity={1000}
            availableQuantity={800}
            costPrice={373.20}
            currentPrice={385.60}
            marketValue={385600}
            profitLoss={12400}
            profitLossPercent={3.32}
            todayProfitLoss={2400}
          />
          <PositionCard
            code="09988.HK"
            name="阿里巴巴"
            quantity={2000}
            availableQuantity={2000}
            costPrice={80.80}
            currentPrice={78.50}
            marketValue={157000}
            profitLoss={-4600}
            profitLossPercent={-2.85}
            todayProfitLoss={-1200}
          />
        </div>
      </div>

      <Separator />

      {/* 交易信号卡片示例 */}
      <div className="space-y-4">
        <h2 className="text-2xl font-bold">交易信号卡片</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          <TradeSignalCard
            id={1}
            stockCode="00700.HK"
            stockName="腾讯控股"
            signalType="buy"
            signalPrice={380.00}
            targetPrice={400.00}
            stopLossPrice={370.00}
            strategyName="突破策略"
            conditionText="价格突破20日均线"
            isExecuted={false}
            createdAt={new Date().toISOString()}
            onExecute={(id) => console.log("执行信号:", id)}
          />
          <TradeSignalCard
            id={2}
            stockCode="09988.HK"
            stockName="阿里巴巴"
            signalType="sell"
            signalPrice={82.00}
            stopLossPrice={85.00}
            strategyName="止盈策略"
            conditionText="达到目标收益率"
            isExecuted={true}
            executedTime={new Date().toISOString()}
            createdAt={new Date(Date.now() - 3600000).toISOString()}
          />
        </div>
      </div>

      <Separator />

      {/* Tabs 示例 */}
      <Card>
        <CardHeader>
          <CardTitle>Tabs 标签页</CardTitle>
          <CardDescription>切换不同内容</CardDescription>
        </CardHeader>
        <CardContent>
          <Tabs defaultValue="overview" className="w-full">
            <TabsList className="grid w-full grid-cols-3">
              <TabsTrigger value="overview">概览</TabsTrigger>
              <TabsTrigger value="positions">持仓</TabsTrigger>
              <TabsTrigger value="signals">信号</TabsTrigger>
            </TabsList>
            <TabsContent value="overview" className="space-y-4">
              <div className="text-sm text-muted-foreground">
                这里显示账户概览信息
              </div>
            </TabsContent>
            <TabsContent value="positions" className="space-y-4">
              <div className="text-sm text-muted-foreground">
                这里显示持仓列表
              </div>
            </TabsContent>
            <TabsContent value="signals" className="space-y-4">
              <div className="text-sm text-muted-foreground">
                这里显示交易信号
              </div>
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>

      {/* Alert 示例 */}
      <div className="space-y-4">
        <h2 className="text-2xl font-bold">Alert 提示</h2>
        <Alert>
          <InfoIcon className="h-4 w-4" />
          <AlertTitle>提示</AlertTitle>
          <AlertDescription>
            这是一条普通的提示信息。
          </AlertDescription>
        </Alert>
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>错误</AlertTitle>
          <AlertDescription>
            交易失败，请检查账户余额是否充足。
          </AlertDescription>
        </Alert>
      </div>

      {/* Progress 和 Skeleton 示例 */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card>
          <CardHeader>
            <CardTitle>Progress 进度条</CardTitle>
            <CardDescription>显示加载进度</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <div className="flex justify-between text-sm">
                <span>数据加载中</span>
                <span>60%</span>
              </div>
              <Progress value={60} />
            </div>
            <div className="space-y-2">
              <div className="flex justify-between text-sm">
                <span>完成</span>
                <span>100%</span>
              </div>
              <Progress value={100} />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Skeleton 骨架屏</CardTitle>
            <CardDescription>加载占位符</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-4 w-1/2" />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Switch 和 Textarea 示例 */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card>
          <CardHeader>
            <CardTitle>Switch 开关</CardTitle>
            <CardDescription>切换开关状态</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <Label htmlFor="auto-trade">自动交易</Label>
              <Switch id="auto-trade" />
            </div>
            <div className="flex items-center justify-between">
              <Label htmlFor="notifications">消息通知</Label>
              <Switch id="notifications" defaultChecked />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Textarea 文本域</CardTitle>
            <CardDescription>多行文本输入</CardDescription>
          </CardHeader>
          <CardContent>
            <Textarea placeholder="输入交易备注..." rows={4} />
          </CardContent>
        </Card>
      </div>

      {/* Tooltip 示例 */}
      <Card>
        <CardHeader>
          <CardTitle>Tooltip 提示框</CardTitle>
          <CardDescription>鼠标悬停显示提示</CardDescription>
        </CardHeader>
        <CardContent className="flex gap-4">
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="secondary">悬停查看提示</Button>
              </TooltipTrigger>
              <TooltipContent>
                <p>这是一个提示信息</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </CardContent>
      </Card>
    </div>
  )
}
