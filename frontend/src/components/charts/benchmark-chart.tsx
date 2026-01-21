"use client";

import { useMemo } from "react";
import {
  Line,
  LineChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  Legend,
  ReferenceLine,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { formatDate, formatPercentage, cn } from "@/lib/utils";
import type { ValuationHistoryPoint } from "@/types/api";

interface BenchmarkDataPoint {
  date: string;
  value: number | null;
}

interface BenchmarkChartProps {
  portfolioData: ValuationHistoryPoint[];
  benchmarkData?: BenchmarkDataPoint[];
  benchmarkName?: string;
  portfolioReturn?: string | null;
  benchmarkReturn?: string | null;
  alpha?: string | null;
  isLoading?: boolean;
  title?: string;
}

interface ChartDataPoint {
  date: string;
  dateFormatted: string;
  portfolioReturn: number | null;
  benchmarkReturn: number | null;
}

export function BenchmarkChart({
  portfolioData,
  benchmarkData = [],
  benchmarkName = "S&P 500",
  portfolioReturn,
  benchmarkReturn,
  alpha,
  isLoading,
  title = "Benchmark Comparison",
}: BenchmarkChartProps) {
  // Normalize both datasets to percentage returns from start
  const chartData = useMemo<ChartDataPoint[]>(() => {
    if (portfolioData.length === 0) return [];

    // Get starting values
    const portfolioStart = portfolioData[0]?.value
      ? parseFloat(portfolioData[0].value)
      : null;

    // Create a map of benchmark data by date for easy lookup
    const benchmarkMap = new Map<string, number>();
    if (benchmarkData.length > 0) {
      const benchmarkStart = benchmarkData[0]?.value;
      benchmarkData.forEach((point) => {
        if (point.value !== null && benchmarkStart !== null) {
          benchmarkMap.set(
            point.date,
            ((point.value - benchmarkStart) / benchmarkStart) * 100
          );
        }
      });
    }

    return portfolioData.map((point) => {
      const portfolioValue = point.value ? parseFloat(point.value) : null;
      const portfolioRet =
        portfolioStart && portfolioValue
          ? ((portfolioValue - portfolioStart) / portfolioStart) * 100
          : null;

      return {
        date: point.date,
        dateFormatted: formatDate(point.date, { month: "short", day: "numeric" }),
        portfolioReturn: portfolioRet,
        benchmarkReturn: benchmarkMap.get(point.date) ?? null,
      };
    });
  }, [portfolioData, benchmarkData]);

  // Calculate Y-axis domain
  const yDomain = useMemo(() => {
    if (chartData.length === 0) return [-10, 10];

    const values = chartData
      .flatMap((d) => [d.portfolioReturn, d.benchmarkReturn])
      .filter((v): v is number => v !== null);

    if (values.length === 0) return [-10, 10];

    const min = Math.min(...values);
    const max = Math.max(...values);
    const padding = Math.max((max - min) * 0.1, 5);

    return [min - padding, max + padding];
  }, [chartData]);

  const portfolioReturnValue = portfolioReturn ? parseFloat(portfolioReturn) * 100 : null;
  const benchmarkReturnValue = benchmarkReturn ? parseFloat(benchmarkReturn) * 100 : null;
  const alphaValue = alpha ? parseFloat(alpha) * 100 : null;

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

  if (portfolioData.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{title}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-64 flex items-center justify-center text-muted-foreground">
            No data available for benchmark comparison
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-2">
          <div>
            <CardTitle>{title}</CardTitle>
            <CardDescription>
              Your portfolio vs. {benchmarkName}
            </CardDescription>
          </div>
          <div className="flex gap-2 flex-wrap">
            {portfolioReturnValue !== null && (
              <Badge
                variant="outline"
                className={cn(
                  "font-mono",
                  portfolioReturnValue >= 0
                    ? "border-green-500 text-green-600 dark:text-green-500"
                    : "border-red-500 text-red-600 dark:text-red-500"
                )}
              >
                Portfolio: {formatPercentage(portfolioReturnValue / 100)}
              </Badge>
            )}
            {benchmarkReturnValue !== null && (
              <Badge variant="outline" className="font-mono">
                {benchmarkName}: {formatPercentage(benchmarkReturnValue / 100)}
              </Badge>
            )}
            {alphaValue !== null && (
              <Badge
                variant={alphaValue >= 0 ? "default" : "destructive"}
                className="font-mono"
              >
                Alpha: {alphaValue >= 0 ? "+" : ""}{formatPercentage(alphaValue / 100)}
              </Badge>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart
              data={chartData}
              margin={{ top: 10, right: 10, left: 0, bottom: 0 }}
            >
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
                tickFormatter={(value) => `${value.toFixed(0)}%`}
                width={50}
              />
              <ReferenceLine
                y={0}
                stroke="hsl(var(--muted-foreground))"
                strokeDasharray="3 3"
              />
              <Tooltip
                content={({ active, payload }) => {
                  if (!active || !payload?.length) return null;
                  const data = payload[0].payload as ChartDataPoint;
                  return (
                    <div className="rounded-lg border bg-background p-3 shadow-md">
                      <p className="text-sm text-muted-foreground mb-2">
                        {formatDate(data.date)}
                      </p>
                      {data.portfolioReturn !== null && (
                        <p className="text-sm">
                          <span
                            className="inline-block w-3 h-3 rounded-full mr-2"
                            style={{ backgroundColor: "hsl(221, 83%, 53%)" }}
                          />
                          <span className="text-muted-foreground">Portfolio: </span>
                          <span
                            className={cn(
                              "font-medium",
                              data.portfolioReturn >= 0
                                ? "text-green-600 dark:text-green-500"
                                : "text-red-600 dark:text-red-500"
                            )}
                          >
                            {formatPercentage(data.portfolioReturn / 100)}
                          </span>
                        </p>
                      )}
                      {data.benchmarkReturn !== null && (
                        <p className="text-sm">
                          <span
                            className="inline-block w-3 h-3 rounded-full mr-2"
                            style={{ backgroundColor: "hsl(var(--muted-foreground))" }}
                          />
                          <span className="text-muted-foreground">{benchmarkName}: </span>
                          <span
                            className={cn(
                              "font-medium",
                              data.benchmarkReturn >= 0
                                ? "text-green-600 dark:text-green-500"
                                : "text-red-600 dark:text-red-500"
                            )}
                          >
                            {formatPercentage(data.benchmarkReturn / 100)}
                          </span>
                        </p>
                      )}
                    </div>
                  );
                }}
              />
              <Legend
                verticalAlign="top"
                height={36}
                formatter={(value) => (
                  <span className="text-sm text-muted-foreground">{value}</span>
                )}
              />
              <Line
                type="monotone"
                dataKey="portfolioReturn"
                name="Portfolio"
                stroke="hsl(221, 83%, 53%)"
                strokeWidth={2}
                dot={false}
                activeDot={{
                  r: 4,
                  fill: "hsl(221, 83%, 53%)",
                  stroke: "hsl(var(--background))",
                  strokeWidth: 2,
                }}
                connectNulls
              />
              <Line
                type="monotone"
                dataKey="benchmarkReturn"
                name={benchmarkName}
                stroke="hsl(var(--muted-foreground))"
                strokeWidth={2}
                strokeDasharray="5 5"
                dot={false}
                activeDot={{
                  r: 4,
                  fill: "hsl(var(--muted-foreground))",
                  stroke: "hsl(var(--background))",
                  strokeWidth: 2,
                }}
                connectNulls
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
}
