"use client";

import { useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  ReferenceLine,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCurrency, formatDate, cn } from "@/lib/utils";
import type { ValuationHistoryPoint } from "@/types/api";

type ChartMode = "value" | "pnl";

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
  pnl: number | null;
  pnlPercentage: number | null;
  periodPerformance: number | null; // Performance % relative to period start
}

export function ValueChart({
  data,
  currency,
  isLoading,
  title = "Portfolio Value",
  showCostBasis = false,
}: ValueChartProps) {
  const [mode, setMode] = useState<ChartMode>("pnl");

  const chartData = useMemo<ChartDataPoint[]>(() => {
    // Get the starting value of the period for calculating relative performance
    const firstPoint = data[0];
    const startValue = firstPoint?.value ? parseFloat(firstPoint.value) : null;

    return data.map((point) => {
      const currentValue = point.value ? parseFloat(point.value) : null;
      // Calculate performance relative to period start
      const periodPerformance = startValue && currentValue
        ? ((currentValue - startValue) / startValue) * 100
        : null;

      return {
        date: point.date,
        dateFormatted: formatDate(point.date, { month: "short", day: "numeric" }),
        value: currentValue,
        costBasis: parseFloat(point.cost_basis),
        pnl: point.total_pnl ? parseFloat(point.total_pnl) : null,
        pnlPercentage: point.pnl_percentage ? parseFloat(point.pnl_percentage) : null,
        periodPerformance,
      };
    });
  }, [data]);

  // Calculate min/max for Y axis
  const { yDomain, zeroPosition } = useMemo(() => {
    let values: number[];

    if (mode === "pnl") {
      values = chartData
        .map((d) => d.periodPerformance)
        .filter((v): v is number => v !== null);
    } else {
      values = chartData
        .flatMap((d) => [d.value, showCostBasis ? d.costBasis : null])
        .filter((v): v is number => v !== null);
    }

    if (values.length === 0) return { yDomain: [0, 100] as [number, number], zeroPosition: 0.5 };

    const min = Math.min(...values);
    const max = Math.max(...values);
    const padding = (max - min) * 0.1 || Math.abs(max) * 0.1 || 1;

    let domain: [number, number];
    if (mode === "pnl") {
      // For Performance, allow negative values and ensure 0 is visible if we cross it
      domain = [min - padding, max + padding];
    } else {
      domain = [Math.max(0, min - padding), max + padding];
    }

    // Calculate where 0 falls as a percentage from TOP (for gradient)
    // Gradient goes from top (0%) to bottom (100%)
    const [domainMin, domainMax] = domain;
    const zeroPos = domainMax <= 0 ? 0 : domainMin >= 0 ? 1 : (domainMax - 0) / (domainMax - domainMin);

    return { yDomain: domain, zeroPosition: zeroPos };
  }, [chartData, showCostBasis, mode]);

  // Determine performance over the selected period
  const performanceInfo = useMemo(() => {
    if (chartData.length < 2) return { isPositive: true, change: 0, changePercent: 0 };

    const first = chartData[0];
    const last = chartData[chartData.length - 1];

    if (mode === "pnl") {
      // Use the period performance of the last point
      const lastPerformance = last?.periodPerformance ?? 0;
      return { isPositive: lastPerformance >= 0, change: lastPerformance, changePercent: lastPerformance };
    }

    const firstValue = first?.value ?? first?.costBasis ?? 0;
    const lastValue = last?.value ?? 0;
    const change = lastValue - firstValue;
    const changePercent = firstValue !== 0 ? (change / firstValue) * 100 : 0;
    return { isPositive: change >= 0, change, changePercent };
  }, [chartData, mode]);

  const { isPositive, change, changePercent } = performanceInfo;

  // Chart colors
  const chartColors = {
    positive: "hsl(142, 76%, 36%)", // Green
    negative: "hsl(0, 84%, 60%)",    // Red
    neutral: "hsl(217, 91%, 60%)",   // Blue
  };
  // Performance mode uses green/red, Value mode uses neutral blue
  const activeColor = mode === "value"
    ? chartColors.neutral
    : isPositive ? chartColors.positive : chartColors.negative;

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
        <div className="flex items-center gap-4">
          <CardTitle>{title}</CardTitle>
          <div className="flex bg-muted rounded-md p-0.5">
            <button
              onClick={() => setMode("pnl")}
              className={cn(
                "text-xs px-3 py-1 h-7 rounded-sm transition-all",
                mode === "pnl"
                  ? "bg-background shadow-sm font-medium"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              Performance
            </button>
            <button
              onClick={() => setMode("value")}
              className={cn(
                "text-xs px-3 py-1 h-7 rounded-sm transition-all",
                mode === "value"
                  ? "bg-background shadow-sm font-medium"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              Value
            </button>
          </div>
        </div>
        {/* Colorblind-accessible performance indicator with text and icon */}
        {chartData.length >= 2 && (
          <div
            className="flex items-center gap-1 text-sm font-medium"
            style={{ color: activeColor }}
            aria-label={`Performance: ${isPositive ? "up" : "down"} ${mode === "pnl" ? `${Math.abs(changePercent).toFixed(2)}%` : formatCurrency(Math.abs(change), currency)}`}
          >
            <span aria-hidden="true">{isPositive ? "▲" : "▼"}</span>
            <span>
              {mode === "pnl"
                ? `${isPositive ? "+" : ""}${changePercent.toFixed(2)}%`
                : `${isPositive ? "+" : "-"}${formatCurrency(Math.abs(change), currency)}`
              }
            </span>
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
                {/* Split gradient for performance mode - green above 0, red below */}
                <linearGradient id="splitLineGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={chartColors.positive} />
                  <stop offset={`${zeroPosition * 100}%`} stopColor={chartColors.positive} />
                  <stop offset={`${zeroPosition * 100}%`} stopColor={chartColors.negative} />
                  <stop offset="100%" stopColor={chartColors.negative} />
                </linearGradient>
                <linearGradient id="splitFillGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={chartColors.positive} stopOpacity={0.3} />
                  <stop offset={`${zeroPosition * 100}%`} stopColor={chartColors.positive} stopOpacity={0.1} />
                  <stop offset={`${zeroPosition * 100}%`} stopColor={chartColors.negative} stopOpacity={0.1} />
                  <stop offset="100%" stopColor={chartColors.negative} stopOpacity={0.3} />
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
                  mode === "pnl"
                    ? `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`
                    : new Intl.NumberFormat("en-US", {
                        notation: "compact",
                        compactDisplay: "short",
                      }).format(value)
                }
                allowDecimals={true}
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
                      {mode === "pnl" ? (
                        <>
                          {data.periodPerformance !== null && (
                            <p
                              className="text-sm font-medium"
                              style={{ color: data.periodPerformance >= 0 ? chartColors.positive : chartColors.negative }}
                            >
                              Performance: {data.periodPerformance >= 0 ? "+" : ""}{data.periodPerformance.toFixed(2)}%
                            </p>
                          )}
                        </>
                      ) : (
                        <>
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
                        </>
                      )}
                    </div>
                  );
                }}
              />
              {mode === "pnl" && (
                <ReferenceLine
                  y={0}
                  stroke="hsl(var(--muted-foreground))"
                  strokeDasharray="3 3"
                  strokeOpacity={0.5}
                />
              )}
              {mode === "value" && showCostBasis && (
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
                dataKey={mode === "pnl" ? "periodPerformance" : "value"}
                stroke={mode === "pnl" ? "url(#splitLineGradient)" : activeColor}
                strokeWidth={2}
                fill={mode === "pnl" ? "url(#splitFillGradient)" : "url(#valueGradient)"}
                dot={false}
                activeDot={(props) => {
                  const { cx, cy, payload } = props as { cx?: number; cy?: number; payload?: ChartDataPoint };
                  if (cx === undefined || cy === undefined || !payload) return null;
                  const dotColor = mode === "pnl" && payload.periodPerformance !== null
                    ? payload.periodPerformance >= 0 ? chartColors.positive : chartColors.negative
                    : activeColor;
                  return (
                    <circle
                      cx={cx}
                      cy={cy}
                      r={4}
                      fill={dotColor}
                      stroke="hsl(var(--background))"
                      strokeWidth={2}
                    />
                  );
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
