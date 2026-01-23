"use client";

import { useMemo, useState } from "react";
import { Cell, Pie, PieChart, ResponsiveContainer, Sector } from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatPercentage } from "@/lib/utils";
import type { AssetClass, HoldingValuation } from "@/types/api";

// Modern, sophisticated colors for each asset class
// Uses oklch for perceptual uniformity, works well in light/dark modes
const ASSET_CLASS_COLORS: Record<AssetClass, string> = {
  ETF: "oklch(0.65 0.19 145)",      // Emerald green - diversified funds (largest)
  STOCK: "oklch(0.55 0.22 260)",    // Indigo blue - individual stocks
  BOND: "oklch(0.70 0.14 55)",      // Warm amber - fixed income stability
  CRYPTO: "oklch(0.60 0.24 300)",   // Violet purple - digital assets
  OPTION: "oklch(0.65 0.20 350)",   // Rose pink - derivatives
  FUTURE: "oklch(0.58 0.18 280)",   // Deep purple - futures
  INDEX: "oklch(0.60 0.16 200)",    // Cyan teal - index funds
  CASH: "oklch(0.75 0.12 85)",      // Soft gold - cash/liquidity
  OTHER: "oklch(0.55 0.02 260)",    // Neutral slate - other/unknown
};

// Display names for asset classes
const ASSET_CLASS_LABELS: Record<AssetClass, string> = {
  STOCK: "Stocks",
  ETF: "ETFs",
  BOND: "Bonds",
  CRYPTO: "Crypto",
  OPTION: "Options",
  FUTURE: "Futures",
  INDEX: "Index Funds",
  CASH: "Cash",
  OTHER: "Other",
};

// Fallback colors for non-asset-class grouping (modern palette)
const COLORS = [
  "oklch(0.55 0.22 260)", // Indigo
  "oklch(0.65 0.19 145)", // Emerald
  "oklch(0.70 0.14 55)",  // Amber
  "oklch(0.60 0.24 300)", // Violet
  "oklch(0.65 0.20 350)", // Rose
  "oklch(0.60 0.16 200)", // Cyan
  "oklch(0.58 0.18 280)", // Purple
  "oklch(0.75 0.12 85)",  // Gold
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
        y={cy - 6}
        textAnchor="middle"
        fill="currentColor"
        className="text-xs font-medium"
      >
        {payload.name}
      </text>
      <text
        x={cx}
        y={cy + 10}
        textAnchor="middle"
        fill="currentColor"
        className="text-sm font-bold"
      >
        {formatPercentage(payload.percentage / 100, { showSign: false })}
      </text>
      <Sector
        cx={cx}
        cy={cy}
        innerRadius={innerRadius}
        outerRadius={outerRadius + 4}
        startAngle={startAngle}
        endAngle={endAngle}
        fill={fill}
      />
      <Sector
        cx={cx}
        cy={cy}
        startAngle={startAngle}
        endAngle={endAngle}
        innerRadius={outerRadius + 6}
        outerRadius={outerRadius + 8}
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
    const groups = new Map<string, { value: number; assetClass?: AssetClass }>();

    holdings.forEach((holding) => {
      const value = holding.current_value.portfolio_amount
        ? parseFloat(holding.current_value.portfolio_amount)
        : 0;

      let key: string;
      let assetClass: AssetClass | undefined;
      switch (groupBy) {
        case "sector":
          key = holding.asset_name?.split(" ")[0] || "Other"; // Simplified
          break;
        case "asset_class":
          assetClass = holding.asset_class || "OTHER";
          key = assetClass;
          break;
        case "ticker":
        default:
          key = holding.ticker;
      }

      const existing = groups.get(key);
      groups.set(key, {
        value: (existing?.value || 0) + value,
        assetClass: assetClass || existing?.assetClass,
      });
    });

    // Calculate total and create chart data
    const total = Array.from(groups.values()).reduce((a, b) => a + b.value, 0);

    if (total === 0) return [];

    return Array.from(groups.entries())
      .map(([key, { value, assetClass }], index) => {
        // For asset_class grouping, use fixed colors and display labels
        const isAssetClassGroup = groupBy === "asset_class" && assetClass;
        const name = isAssetClassGroup ? ASSET_CLASS_LABELS[assetClass] : key;
        const color = isAssetClassGroup
          ? ASSET_CLASS_COLORS[assetClass]
          : COLORS[index % COLORS.length];

        return {
          name,
          value,
          percentage: (value / total) * 100,
          color,
        };
      })
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
        <div className="flex items-start gap-6">
          {/* Chart */}
          <div className="h-40 w-40 shrink-0">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={chartData}
                  cx="50%"
                  cy="50%"
                  innerRadius={40}
                  outerRadius={60}
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
          <div className="flex-1 min-w-0" role="list" aria-label="Chart legend">
            <div className="space-y-1.5">
              {chartData.map((item, index) => (
                <div
                  key={item.name}
                  role="listitem"
                  tabIndex={0}
                  className="flex items-center gap-2 text-sm cursor-pointer hover:bg-muted/50 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-1 rounded px-1.5 py-1 -mx-1.5 transition-colors"
                  onMouseEnter={() => setActiveIndex(index)}
                  onMouseLeave={() => setActiveIndex(undefined)}
                  onFocus={() => setActiveIndex(index)}
                  onBlur={() => setActiveIndex(undefined)}
                  aria-label={`${item.name}: ${formatPercentage(item.percentage / 100, { showSign: false })}`}
                >
                  <div
                    className="w-2.5 h-2.5 rounded-full shrink-0"
                    style={{ backgroundColor: item.color }}
                    aria-hidden="true"
                  />
                  <span className="flex-1 font-medium">{item.name}</span>
                  <span className="text-muted-foreground tabular-nums">
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
