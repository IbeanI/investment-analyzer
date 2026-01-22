"use client";

import { useMemo, useState } from "react";
import { Cell, Pie, PieChart, ResponsiveContainer, Sector } from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatPercentage } from "@/lib/utils";
import type { HoldingValuation } from "@/types/api";

// Chart colors - accessible and colorblind-friendly
const COLORS = [
  "hsl(221, 83%, 53%)", // Blue
  "hsl(142, 71%, 45%)", // Green
  "hsl(38, 92%, 50%)",  // Orange
  "hsl(262, 83%, 58%)", // Purple
  "hsl(0, 84%, 60%)",   // Red
  "hsl(173, 80%, 40%)", // Teal
  "hsl(340, 75%, 55%)", // Pink
  "hsl(47, 96%, 53%)",  // Yellow
];

interface AllocationChartProps {
  holdings: HoldingValuation[];
  currency: string;
  groupBy?: "ticker" | "sector" | "asset_class";
  isLoading?: boolean;
  title?: string;
}

interface ChartDataPoint {
  name: string;
  value: number;
  percentage: number;
  color: string;
  [key: string]: string | number;
}

// Props for Recharts active shape - Recharts doesn't export proper types for this
interface ActiveShapeProps {
  cx: number;
  cy: number;
  innerRadius: number;
  outerRadius: number;
  startAngle: number;
  endAngle: number;
  fill: string;
  payload: ChartDataPoint;
  currency: string;
}

// Custom active shape for the donut
const renderActiveShape = (props: ActiveShapeProps) => {
  const {
    cx,
    cy,
    innerRadius,
    outerRadius,
    startAngle,
    endAngle,
    fill,
    payload,
    currency: _currency,
  } = props;

  return (
    <g>
      <text
        x={cx}
        y={cy - 10}
        textAnchor="middle"
        fill="currentColor"
        className="text-sm font-medium"
      >
        {payload.name}
      </text>
      <text
        x={cx}
        y={cy + 10}
        textAnchor="middle"
        fill="currentColor"
        className="text-lg font-bold"
      >
        {formatPercentage(payload.percentage / 100, { showSign: false })}
      </text>
      <Sector
        cx={cx}
        cy={cy}
        innerRadius={innerRadius}
        outerRadius={outerRadius + 6}
        startAngle={startAngle}
        endAngle={endAngle}
        fill={fill}
      />
      <Sector
        cx={cx}
        cy={cy}
        startAngle={startAngle}
        endAngle={endAngle}
        innerRadius={outerRadius + 8}
        outerRadius={outerRadius + 10}
        fill={fill}
      />
    </g>
  );
};

export function AllocationChart({
  holdings,
  currency,
  groupBy = "ticker",
  isLoading,
  title = "Allocation",
}: AllocationChartProps) {
  const [activeIndex, setActiveIndex] = useState<number | undefined>(undefined);

  const chartData = useMemo<ChartDataPoint[]>(() => {
    if (holdings.length === 0) return [];

    // Group holdings by the specified field
    const groups = new Map<string, number>();

    holdings.forEach((holding) => {
      const value = holding.current_value.portfolio_amount
        ? parseFloat(holding.current_value.portfolio_amount)
        : 0;

      let key: string;
      switch (groupBy) {
        case "sector":
          key = holding.asset_name?.split(" ")[0] || "Other"; // Simplified
          break;
        case "asset_class":
          key = "Stock"; // Would need asset_class from API
          break;
        case "ticker":
        default:
          key = holding.ticker;
      }

      groups.set(key, (groups.get(key) || 0) + value);
    });

    // Calculate total and create chart data
    const total = Array.from(groups.values()).reduce((a, b) => a + b, 0);

    if (total === 0) return [];

    return Array.from(groups.entries())
      .map(([name, value], index) => ({
        name,
        value,
        percentage: (value / total) * 100,
        color: COLORS[index % COLORS.length],
      }))
      .sort((a, b) => b.value - a.value)
      .slice(0, 8); // Limit to 8 items
  }, [holdings, groupBy]);

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{title}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-center">
            <Skeleton className="h-48 w-48 rounded-full" />
          </div>
        </CardContent>
      </Card>
    );
  }

  if (chartData.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{title}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-48 flex items-center justify-center text-muted-foreground">
            No holdings data available
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col md:flex-row items-center gap-6">
          {/* Chart */}
          <div className="h-48 w-48 shrink-0">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={chartData}
                  cx="50%"
                  cy="50%"
                  innerRadius={50}
                  outerRadius={70}
                  paddingAngle={2}
                  dataKey="value"
                  activeShape={(props: unknown) =>
                    renderActiveShape({ ...(props as ActiveShapeProps), currency })
                  }
                  onMouseEnter={(_, index) => setActiveIndex(index)}
                  onMouseLeave={() => setActiveIndex(undefined)}
                  {...({ activeIndex } as Record<string, unknown>)}
                >
                  {chartData.map((entry, index) => (
                    <Cell
                      key={`cell-${index}`}
                      fill={entry.color}
                      stroke="hsl(var(--background))"
                      strokeWidth={2}
                    />
                  ))}
                </Pie>
              </PieChart>
            </ResponsiveContainer>
          </div>

          {/* Legend */}
          <div className="flex-1 w-full">
            <div className="grid grid-cols-2 gap-2">
              {chartData.map((item, index) => (
                <div
                  key={item.name}
                  className="flex items-center gap-2 text-sm cursor-pointer hover:opacity-80"
                  onMouseEnter={() => setActiveIndex(index)}
                  onMouseLeave={() => setActiveIndex(undefined)}
                >
                  <div
                    className="w-3 h-3 rounded-full shrink-0"
                    style={{ backgroundColor: item.color }}
                  />
                  <span className="truncate flex-1">{item.name}</span>
                  <span className="text-muted-foreground">
                    {formatPercentage(item.percentage / 100, { showSign: false })}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
