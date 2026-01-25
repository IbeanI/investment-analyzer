"use client";

import { useMemo } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { formatDate, formatPercentage } from "@/lib/utils";
import type { DrawdownPeriod, ValuationHistoryPoint } from "@/types/api";

interface DrawdownChartProps {
  data: ValuationHistoryPoint[];
  maxDrawdown?: string | null;
  maxDrawdownStart?: string | null;
  maxDrawdownEnd?: string | null;
  currentDrawdown?: string | null;
  drawdownPeriods?: DrawdownPeriod[];
  isLoading?: boolean;
  title?: string;
}

interface ChartDataPoint {
  date: string;
  dateFormatted: string;
  drawdown: number;
}

export function DrawdownChart({
  data,
  maxDrawdown,
  maxDrawdownStart: _maxDrawdownStart,
  maxDrawdownEnd: _maxDrawdownEnd,
  currentDrawdown,
  drawdownPeriods = [],
  isLoading,
  title = "Drawdown Analysis",
}: DrawdownChartProps) {
  // Use API-provided TWR-based drawdown for each point
  const chartData = useMemo<ChartDataPoint[]>(() => {
    if (data.length === 0) return [];

    // Filter out gap periods - they have no holdings and would show misleading data
    const validData = data.filter(point => !point.is_gap_period);

    if (validData.length === 0) return [];

    return validData.map((point) => {
      // Use API-provided TWR-based drawdown (already accounts for cash flows)
      const drawdown = point.drawdown !== null && point.drawdown !== undefined
        ? parseFloat(point.drawdown) * 100
        : 0;

      return {
        date: point.date,
        dateFormatted: formatDate(point.date, { month: "short", day: "numeric" }),
        drawdown,
      };
    });
  }, [data]);

  // Find min drawdown from chart data (visual minimum)
  const chartMinDrawdown = useMemo(() => {
    if (chartData.length === 0) return null;
    return Math.min(...chartData.map((d) => d.drawdown));
  }, [chartData]);

  // API-provided max drawdown (from true historical peak)
  const maxDrawdownValue = maxDrawdown ? parseFloat(maxDrawdown) * 100 : null;
  const currentDrawdownValue = currentDrawdown ? parseFloat(currentDrawdown) * 100 : null;

  // Only show reference line if it's within the visible chart range
  // (API's max drawdown may be from a peak before the visible data starts)
  const showMaxDrawdownLine = maxDrawdownValue !== null &&
    chartMinDrawdown !== null &&
    Math.abs(maxDrawdownValue - chartMinDrawdown) < 1; // Within 1% tolerance

  // Find min drawdown for Y-axis - use the lower of API value or chart min
  const yDomain = useMemo(() => {
    if (chartMinDrawdown === null) return [-20, 0];
    const minValue = maxDrawdownValue !== null
      ? Math.min(chartMinDrawdown, maxDrawdownValue)
      : chartMinDrawdown;
    // Add 10% padding below
    return [Math.min(minValue * 1.1, -5), 0];
  }, [chartMinDrawdown, maxDrawdownValue]);

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{title}</CardTitle>
        </CardHeader>
        <CardContent>
          <Skeleton className="h-64 w-full" />
        </CardContent>
      </Card>
    );
  }

  // Check if we have valid data after filtering gap periods
  if (data.length === 0 || chartData.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{title}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-64 flex items-center justify-center text-muted-foreground">
            No data available for drawdown analysis
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
          <div>
            <CardTitle>{title}</CardTitle>
            <CardDescription>
              Peak-to-trough decline in portfolio value
            </CardDescription>
          </div>
          <div className="flex gap-2 flex-wrap">
            {maxDrawdownValue !== null && (
              <Badge variant="destructive" className="font-mono">
                Max: {formatPercentage(maxDrawdownValue / 100)}
              </Badge>
            )}
            {currentDrawdownValue !== null && currentDrawdownValue < 0 && (
              <Badge variant="outline" className="font-mono">
                Current: {formatPercentage(currentDrawdownValue / 100)}
              </Badge>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart
              data={chartData}
              margin={{ top: 10, right: 10, left: 0, bottom: 0 }}
            >
              <defs>
                <linearGradient id="drawdownGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop
                    offset="5%"
                    stopColor="hsl(0, 84%, 60%)"
                    stopOpacity={0.4}
                  />
                  <stop
                    offset="95%"
                    stopColor="hsl(0, 84%, 60%)"
                    stopOpacity={0.1}
                  />
                </linearGradient>
              </defs>
              <CartesianGrid
                strokeDasharray="3 3"
                vertical={false}
                stroke="var(--border)"
              />
              <XAxis
                dataKey="dateFormatted"
                axisLine={false}
                tickLine={false}
                tick={{ fontSize: 12, fill: "var(--muted-foreground)" }}
                tickMargin={8}
                minTickGap={30}
              />
              <YAxis
                domain={yDomain}
                axisLine={false}
                tickLine={false}
                tick={{ fontSize: 12, fill: "var(--muted-foreground)" }}
                tickFormatter={(value) => `${value.toFixed(0)}%`}
                width={50}
              />
              <ReferenceLine
                y={0}
                stroke="hsl(var(--muted-foreground))"
                strokeDasharray="3 3"
              />
              {showMaxDrawdownLine && maxDrawdownValue !== null && (
                <ReferenceLine
                  y={maxDrawdownValue}
                  stroke="hsl(0, 84%, 50%)"
                  strokeDasharray="5 5"
                  strokeWidth={2}
                  label={{
                    value: "Max DD",
                    position: "right",
                    fill: "hsl(0, 84%, 50%)",
                    fontSize: 11,
                  }}
                />
              )}
              <Tooltip
                content={({ active, payload }) => {
                  if (!active || !payload?.length) return null;
                  const data = payload[0].payload as ChartDataPoint;
                  return (
                    <div className="rounded-lg border bg-background p-3 shadow-md">
                      <p className="text-sm text-muted-foreground mb-1">
                        {formatDate(data.date)}
                      </p>
                      <p className="text-sm font-medium text-red-600 dark:text-red-500">
                        Drawdown: {formatPercentage(data.drawdown / 100)}
                      </p>
                    </div>
                  );
                }}
              />
              <Area
                type="monotone"
                dataKey="drawdown"
                stroke="hsl(0, 84%, 60%)"
                strokeWidth={2}
                fill="url(#drawdownGradient)"
                dot={false}
                connectNulls
                isAnimationActive={true}
                animationBegin={0}
                animationDuration={900}
                animationEasing="ease-out"
                activeDot={{
                  r: 4,
                  fill: "hsl(0, 84%, 60%)",
                  stroke: "var(--background)",
                  strokeWidth: 2,
                }}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* Drawdown Periods Table */}
        {drawdownPeriods.length > 0 && (
          <div className="space-y-2">
            <h4 className="text-sm font-medium">Significant Drawdown Periods</h4>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b">
                    <th className="text-left py-2 pr-4 font-medium text-muted-foreground">Period</th>
                    <th className="text-right py-2 px-4 font-medium text-muted-foreground">Depth</th>
                    <th className="text-right py-2 px-4 font-medium text-muted-foreground">Duration</th>
                    <th className="text-right py-2 pl-4 font-medium text-muted-foreground">Recovery</th>
                  </tr>
                </thead>
                <tbody>
                  {drawdownPeriods.slice(0, 5).map((period, index) => (
                    <tr key={index} className="border-b last:border-0">
                      <td className="py-2 pr-4">
                        <span className="text-muted-foreground">
                          {formatDate(period.start_date, { month: "short", day: "numeric", year: "2-digit" })}
                        </span>
                        <span className="mx-1">→</span>
                        <span className="text-muted-foreground">
                          {formatDate(period.trough_date, { month: "short", day: "numeric", year: "2-digit" })}
                        </span>
                      </td>
                      <td className="text-right py-2 px-4 font-mono text-red-600 dark:text-red-500">
                        {formatPercentage(parseFloat(period.depth))}
                      </td>
                      <td className="text-right py-2 px-4 text-muted-foreground">
                        {period.duration_days}d
                      </td>
                      <td className="text-right py-2 pl-4">
                        {period.recovery_days !== null ? (
                          <span className="text-green-600 dark:text-green-500">
                            {period.recovery_days}d
                          </span>
                        ) : (
                          <span className="text-muted-foreground">ongoing</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
