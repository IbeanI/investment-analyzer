"use client";

import { useMemo } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCurrency, formatDate } from "@/lib/utils";
import type { ValuationHistoryPoint } from "@/types/api";

interface ValueChartProps {
  data: ValuationHistoryPoint[];
  currency: string;
  isLoading?: boolean;
  title?: string;
  showCostBasis?: boolean;
}

interface ChartDataPoint {
  date: string;
  dateFormatted: string;
  value: number | null;
  costBasis: number;
}

export function ValueChart({
  data,
  currency,
  isLoading,
  title = "Portfolio Value",
  showCostBasis = false,
}: ValueChartProps) {
  const chartData = useMemo<ChartDataPoint[]>(() => {
    return data.map((point) => ({
      date: point.date,
      dateFormatted: formatDate(point.date, { month: "short", day: "numeric" }),
      value: point.value ? parseFloat(point.value) : null,
      costBasis: parseFloat(point.cost_basis),
    }));
  }, [data]);

  // Calculate min/max for Y axis
  const yDomain = useMemo(() => {
    const values = chartData
      .flatMap((d) => [d.value, showCostBasis ? d.costBasis : null])
      .filter((v): v is number => v !== null);

    if (values.length === 0) return [0, 100];

    const min = Math.min(...values);
    const max = Math.max(...values);
    const padding = (max - min) * 0.1;

    return [Math.max(0, min - padding), max + padding];
  }, [chartData, showCostBasis]);

  // Determine if portfolio is up or down overall
  const performanceInfo = useMemo(() => {
    if (chartData.length < 2) return { isPositive: true, change: 0, changePercent: 0 };
    const first = chartData[0]?.value ?? chartData[0]?.costBasis ?? 0;
    const last = chartData[chartData.length - 1]?.value ?? 0;
    const change = last - first;
    const changePercent = first !== 0 ? (change / first) * 100 : 0;
    return { isPositive: last >= first, change, changePercent };
  }, [chartData]);

  const { isPositive, change, changePercent } = performanceInfo;

  // Traditional green/red colors for gain/loss
  // Accessibility is provided via the text indicator with arrow symbol
  const chartColors = {
    positive: "hsl(142, 76%, 36%)", // Green
    negative: "hsl(0, 84%, 60%)",    // Red
  };
  const activeColor = isPositive ? chartColors.positive : chartColors.negative;

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

  if (data.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{title}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-64 flex items-center justify-center text-muted-foreground">
            No data available for the selected period
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle>{title}</CardTitle>
        {/* Colorblind-accessible performance indicator with text and icon */}
        {chartData.length >= 2 && (
          <div
            className="flex items-center gap-1 text-sm font-medium"
            style={{ color: activeColor }}
            aria-label={`Performance: ${isPositive ? "up" : "down"} ${Math.abs(changePercent).toFixed(2)}%`}
          >
            <span aria-hidden="true">{isPositive ? "▲" : "▼"}</span>
            <span>{isPositive ? "+" : ""}{changePercent.toFixed(2)}%</span>
          </div>
        )}
      </CardHeader>
      <CardContent>
        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart
              data={chartData}
              margin={{ top: 10, right: 10, left: 0, bottom: 0 }}
            >
              <defs>
                <linearGradient id="valueGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop
                    offset="5%"
                    stopColor={activeColor}
                    stopOpacity={0.3}
                  />
                  <stop
                    offset="95%"
                    stopColor={activeColor}
                    stopOpacity={0}
                  />
                </linearGradient>
              </defs>
              <CartesianGrid
                strokeDasharray="3 3"
                vertical={false}
                stroke="hsl(var(--border))"
              />
              <XAxis
                dataKey="dateFormatted"
                axisLine={false}
                tickLine={false}
                tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }}
                tickMargin={8}
                minTickGap={30}
              />
              <YAxis
                domain={yDomain}
                axisLine={false}
                tickLine={false}
                tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }}
                tickFormatter={(value) =>
                  new Intl.NumberFormat("en-US", {
                    notation: "compact",
                    compactDisplay: "short",
                  }).format(value)
                }
                width={60}
              />
              <Tooltip
                content={({ active, payload }) => {
                  if (!active || !payload?.length) return null;
                  const data = payload[0].payload as ChartDataPoint;
                  return (
                    <div className="rounded-lg border bg-background p-3 shadow-md">
                      <p className="text-sm text-muted-foreground mb-1">
                        {formatDate(data.date)}
                      </p>
                      {data.value !== null && (
                        <p className="text-sm font-medium">
                          Value: {formatCurrency(data.value, currency)}
                        </p>
                      )}
                      {showCostBasis && (
                        <p className="text-sm text-muted-foreground">
                          Cost: {formatCurrency(data.costBasis, currency)}
                        </p>
                      )}
                    </div>
                  );
                }}
              />
              {showCostBasis && (
                <Area
                  type="monotone"
                  dataKey="costBasis"
                  stroke="hsl(var(--muted-foreground))"
                  strokeWidth={1}
                  strokeDasharray="4 4"
                  fill="none"
                  dot={false}
                  activeDot={false}
                />
              )}
              <Area
                type="monotone"
                dataKey="value"
                stroke={activeColor}
                strokeWidth={2}
                fill="url(#valueGradient)"
                dot={false}
                activeDot={{
                  r: 4,
                  fill: activeColor,
                  stroke: "hsl(var(--background))",
                  strokeWidth: 2,
                }}
                connectNulls
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
}
