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
  pnlPercentage: number | null; // P&L as % of cost basis (true investment return)
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
    return data.map((point) => {
      // Backend returns pnl_percentage as decimal ratio (0.1735 = 17.35%), convert to percentage
      const pnlPct = point.pnl_percentage ? parseFloat(point.pnl_percentage) * 100 : null;
      return {
        date: point.date,
        dateFormatted: formatDate(point.date, { month: "short", day: "numeric" }),
        value: point.value ? parseFloat(point.value) : null,
        costBasis: parseFloat(point.cost_basis),
        pnl: point.total_pnl ? parseFloat(point.total_pnl) : null,
        pnlPercentage: pnlPct,
      };
    });
  }, [data]);

  // Calculate nice Y axis domain and ticks
  const { yDomain, yTicks, zeroPosition } = useMemo(() => {
    let values: number[];

    if (mode === "pnl") {
      values = chartData
        .map((d) => d.pnlPercentage)
        .filter((v): v is number => v !== null);
    } else {
      values = chartData
        .flatMap((d) => [d.value, showCostBasis ? d.costBasis : null])
        .filter((v): v is number => v !== null);
    }

    if (values.length === 0) {
      return { yDomain: [0, 100] as [number, number], yTicks: [0, 50, 100], zeroPosition: 0.5 };
    }

    const dataMin = Math.min(...values);
    const dataMax = Math.max(...values);
    const range = dataMax - dataMin;

    // Calculate a nice tick interval
    const getNiceTickInterval = (r: number): number => {
      if (r === 0) return 1;
      const magnitude = Math.pow(10, Math.floor(Math.log10(r)));
      const normalized = r / magnitude;

      let interval: number;
      if (normalized <= 1.5) interval = 0.2 * magnitude;
      else if (normalized <= 3) interval = 0.5 * magnitude;
      else if (normalized <= 7) interval = 1 * magnitude;
      else interval = 2 * magnitude;

      // For percentages, use clean intervals that work at any scale
      if (mode === "pnl") {
        // Nice intervals: 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, ...
        const niceIntervals = [0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100];
        interval = niceIntervals.find(n => n >= interval) ?? interval;
      }

      return interval;
    };

    const tickInterval = getNiceTickInterval(range || 1);

    // Round min down and max up to nice tick values
    let niceMin = Math.floor(dataMin / tickInterval) * tickInterval;
    let niceMax = Math.ceil(dataMax / tickInterval) * tickInterval;

    // For pnl mode, ensure 0 is included if data crosses it or is close
    if (mode === "pnl") {
      if (dataMin < 0 && dataMax > 0) {
        // Data crosses zero - ensure 0 is a tick
      } else if (dataMin >= 0 && dataMin < tickInterval) {
        // Data is positive but close to 0 - include 0
        niceMin = 0;
      } else if (dataMax <= 0 && dataMax > -tickInterval) {
        // Data is negative but close to 0 - include 0
        niceMax = 0;
      }
    } else {
      // For value mode, don't go below 0
      niceMin = Math.max(0, niceMin);
    }

    // Generate tick values
    const ticks: number[] = [];
    for (let tick = niceMin; tick <= niceMax + tickInterval / 2; tick += tickInterval) {
      ticks.push(Math.round(tick * 1000) / 1000); // Avoid floating point issues
    }

    // Ensure we have at least 3 ticks
    if (ticks.length < 3) {
      const midTick = (niceMin + niceMax) / 2;
      ticks.splice(1, 0, midTick);
    }

    const domain: [number, number] = [niceMin, niceMax];

    // Calculate where 0 falls as a percentage from TOP (for gradient)
    // IMPORTANT: Use actual data bounds (dataMin/dataMax), not axis domain (niceMin/niceMax)
    // because SVG gradients map to the path's bounding box, not the chart area
    const zeroPos = dataMax <= 0 ? 0 : dataMin >= 0 ? 1 : dataMax / (dataMax - dataMin);

    return { yDomain: domain, yTicks: ticks, zeroPosition: zeroPos };
  }, [chartData, showCostBasis, mode]);

  // Determine performance info for the selected period
  const performanceInfo = useMemo(() => {
    if (chartData.length < 2) return { isPositive: true, change: 0, changePercent: 0 };

    const first = chartData[0];
    const last = chartData[chartData.length - 1];

    if (mode === "pnl") {
      // Show the CHANGE in P&L percentage during the period
      const firstPnlPct = first?.pnlPercentage ?? 0;
      const lastPnlPct = last?.pnlPercentage ?? 0;
      const periodChange = lastPnlPct - firstPnlPct;
      return { isPositive: periodChange >= 0, change: periodChange, changePercent: periodChange };
    }

    // For value mode, show the change in portfolio value during the period
    const firstValue = first?.value ?? 0;
    const lastValue = last?.value ?? 0;
    const valueChange = lastValue - firstValue;
    const changePercent = firstValue !== 0 ? (valueChange / firstValue) * 100 : 0;
    return { isPositive: valueChange >= 0, change: valueChange, changePercent };
  }, [chartData, mode]);

  const { isPositive, change, changePercent } = performanceInfo;

  // Generate a key that changes when mode or data changes to trigger full redraw animation
  const chartKey = useMemo(() => {
    const dataSignature = chartData.length > 0
      ? `${chartData[0]?.date}-${chartData[chartData.length - 1]?.date}-${chartData.length}`
      : "empty";
    return `${mode}-${dataSignature}`;
  }, [mode, chartData]);

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
              key={chartKey}
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
                {/* Split gradient for performance mode - green at/above 0, red below */}
                <linearGradient id="splitLineGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={chartColors.positive} />
                  <stop offset={`${Math.min(100, zeroPosition * 100 + 0.5)}%`} stopColor={chartColors.positive} />
                  <stop offset={`${Math.min(100, zeroPosition * 100 + 0.5)}%`} stopColor={chartColors.negative} />
                  <stop offset="100%" stopColor={chartColors.negative} />
                </linearGradient>
                <linearGradient id="splitFillGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={chartColors.positive} stopOpacity={0.3} />
                  <stop offset={`${Math.min(100, zeroPosition * 100 + 0.5)}%`} stopColor={chartColors.positive} stopOpacity={0.1} />
                  <stop offset={`${Math.min(100, zeroPosition * 100 + 0.5)}%`} stopColor={chartColors.negative} stopOpacity={0.1} />
                  <stop offset="100%" stopColor={chartColors.negative} stopOpacity={0.3} />
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
                ticks={yTicks}
                axisLine={false}
                tickLine={false}
                tick={{ fontSize: 12, fill: "var(--muted-foreground)" }}
                tickFormatter={(value) => {
                  if (mode === "pnl") {
                    const sign = value >= 0 ? "+" : "";
                    // Determine decimal places based on value magnitude
                    let formatted: string;
                    if (Number.isInteger(value)) {
                      formatted = value.toString();
                    } else if (Math.abs(value) < 0.1) {
                      formatted = value.toFixed(2);
                    } else if (Math.abs(value) < 1) {
                      formatted = value.toFixed(1);
                    } else {
                      formatted = value.toFixed(Math.abs(value % 1) < 0.01 ? 0 : 1);
                    }
                    return `${sign}${formatted}%`;
                  }
                  return new Intl.NumberFormat("en-US", {
                    notation: "compact",
                    compactDisplay: "short",
                  }).format(value);
                }}
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
                          {data.pnlPercentage !== null && (
                            <p
                              className="text-sm font-medium"
                              style={{ color: data.pnlPercentage >= 0 ? chartColors.positive : chartColors.negative }}
                            >
                              P&L: {data.pnlPercentage >= 0 ? "+" : ""}{data.pnlPercentage.toFixed(2)}%
                            </p>
                          )}
                          {data.pnl !== null && (
                            <p className="text-sm text-muted-foreground">
                              {data.pnl >= 0 ? "+" : ""}{formatCurrency(data.pnl, currency)}
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
                  stroke="var(--muted-foreground)"
                  strokeDasharray="3 3"
                  strokeOpacity={0.5}
                />
              )}
              {mode === "value" && showCostBasis && (
                <Area
                  type="monotone"
                  dataKey="costBasis"
                  stroke="var(--muted-foreground)"
                  strokeWidth={1}
                  strokeDasharray="4 4"
                  fill="none"
                  dot={false}
                  activeDot={false}
                  isAnimationActive={true}
                  animationDuration={900}
                  animationEasing="ease-out"
                />
              )}
              <Area
                type="monotone"
                dataKey={mode === "pnl" ? "pnlPercentage" : "value"}
                stroke={mode === "pnl" ? "url(#splitLineGradient)" : activeColor}
                strokeWidth={2}
                fill={mode === "pnl" ? "url(#splitFillGradient)" : "url(#valueGradient)"}
                dot={false}
                isAnimationActive={true}
                animationDuration={900}
                animationEasing="ease-out"
                activeDot={(props) => {
                  const { cx, cy, payload } = props as { cx?: number; cy?: number; payload?: ChartDataPoint };
                  if (cx === undefined || cy === undefined || !payload) return null;
                  const dotColor = mode === "pnl" && payload.pnlPercentage !== null
                    ? payload.pnlPercentage >= 0 ? chartColors.positive : chartColors.negative
                    : activeColor;
                  return (
                    <circle
                      cx={cx}
                      cy={cy}
                      r={4}
                      fill={dotColor}
                      stroke="var(--background)"
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
