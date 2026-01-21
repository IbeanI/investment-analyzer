"use client";

import { TrendingUp, TrendingDown, Minus, Activity, Target, Shield } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, formatPercentage, formatCurrency } from "@/lib/utils";
import type { PerformanceMetrics, RiskMetrics, BenchmarkMetrics } from "@/types/api";

interface PerformanceSummaryProps {
  performance?: PerformanceMetrics | null;
  risk?: RiskMetrics | null;
  benchmark?: BenchmarkMetrics | null;
  currency: string;
  isLoading?: boolean;
}

interface SummaryItemProps {
  label: string;
  value: string | null;
  trend?: "up" | "down" | "neutral";
  isLoading?: boolean;
}

function SummaryItem({ label, value, trend, isLoading }: SummaryItemProps) {
  if (isLoading) {
    return (
      <div className="flex flex-col gap-1">
        <span className="text-xs text-muted-foreground">{label}</span>
        <Skeleton className="h-6 w-16" />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <div className="flex items-center gap-1">
        {trend === "up" && (
          <TrendingUp className="h-3.5 w-3.5 text-green-600 dark:text-green-500" />
        )}
        {trend === "down" && (
          <TrendingDown className="h-3.5 w-3.5 text-red-600 dark:text-red-500" />
        )}
        {trend === "neutral" && (
          <Minus className="h-3.5 w-3.5 text-muted-foreground" />
        )}
        <span
          className={cn(
            "text-sm font-semibold",
            trend === "up" && "text-green-600 dark:text-green-500",
            trend === "down" && "text-red-600 dark:text-red-500"
          )}
        >
          {value ?? "—"}
        </span>
      </div>
    </div>
  );
}

function getTrend(value: string | null | undefined): "up" | "down" | "neutral" {
  if (!value) return "neutral";
  const num = parseFloat(value);
  if (isNaN(num) || num === 0) return "neutral";
  return num > 0 ? "up" : "down";
}

export function PerformanceSummary({
  performance,
  risk,
  benchmark,
  currency,
  isLoading,
}: PerformanceSummaryProps) {
  const formatPct = (value: string | null | undefined): string | null => {
    if (!value) return null;
    const num = parseFloat(value);
    if (isNaN(num)) return null;
    return formatPercentage(num);
  };

  const formatRatio = (value: string | null | undefined): string | null => {
    if (!value) return null;
    const num = parseFloat(value);
    if (isNaN(num)) return null;
    return num.toFixed(2);
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <Activity className="h-4 w-4" />
          Performance Summary
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
          {/* Performance */}
          <SummaryItem
            label="Total Return"
            value={formatPct(performance?.simple_return)}
            trend={getTrend(performance?.simple_return)}
            isLoading={isLoading}
          />
          <SummaryItem
            label="CAGR"
            value={formatPct(performance?.cagr)}
            trend={getTrend(performance?.cagr)}
            isLoading={isLoading}
          />

          {/* Risk */}
          <SummaryItem
            label="Volatility"
            value={formatPct(risk?.volatility_annualized)}
            isLoading={isLoading}
          />
          <SummaryItem
            label="Sharpe"
            value={formatRatio(risk?.sharpe_ratio)}
            trend={
              risk?.sharpe_ratio
                ? parseFloat(risk.sharpe_ratio) >= 1
                  ? "up"
                  : parseFloat(risk.sharpe_ratio) < 0.5
                    ? "down"
                    : "neutral"
                : "neutral"
            }
            isLoading={isLoading}
          />

          {/* Max Drawdown */}
          <SummaryItem
            label="Max Drawdown"
            value={formatPct(risk?.max_drawdown)}
            trend="down"
            isLoading={isLoading}
          />

          {/* Alpha */}
          <SummaryItem
            label="Alpha"
            value={formatPct(benchmark?.alpha)}
            trend={getTrend(benchmark?.alpha)}
            isLoading={isLoading}
          />
        </div>
      </CardContent>
    </Card>
  );
}

// Compact version for dashboard
export function PerformanceSummaryCompact({
  performance,
  risk,
  benchmark,
  isLoading,
}: Omit<PerformanceSummaryProps, "currency">) {
  const formatPct = (value: string | null | undefined): string | null => {
    if (!value) return null;
    const num = parseFloat(value);
    if (isNaN(num)) return null;
    return formatPercentage(num);
  };

  const formatRatio = (value: string | null | undefined): string | null => {
    if (!value) return null;
    const num = parseFloat(value);
    if (isNaN(num)) return null;
    return num.toFixed(2);
  };

  return (
    <div className="grid grid-cols-3 gap-4 p-4 bg-muted/30 rounded-lg border">
      {/* Performance Section */}
      <div className="space-y-2">
        <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
          <TrendingUp className="h-3 w-3" />
          Performance
        </div>
        <div className="space-y-1">
          <SummaryItem
            label="Return"
            value={formatPct(performance?.simple_return)}
            trend={getTrend(performance?.simple_return)}
            isLoading={isLoading}
          />
          <SummaryItem
            label="CAGR"
            value={formatPct(performance?.cagr)}
            trend={getTrend(performance?.cagr)}
            isLoading={isLoading}
          />
        </div>
      </div>

      {/* Risk Section */}
      <div className="space-y-2">
        <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
          <Shield className="h-3 w-3" />
          Risk
        </div>
        <div className="space-y-1">
          <SummaryItem
            label="Volatility"
            value={formatPct(risk?.volatility_annualized)}
            isLoading={isLoading}
          />
          <SummaryItem
            label="Sharpe"
            value={formatRatio(risk?.sharpe_ratio)}
            trend={
              risk?.sharpe_ratio
                ? parseFloat(risk.sharpe_ratio) >= 1
                  ? "up"
                  : "neutral"
                : "neutral"
            }
            isLoading={isLoading}
          />
        </div>
      </div>

      {/* Benchmark Section */}
      <div className="space-y-2">
        <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
          <Target className="h-3 w-3" />
          vs Benchmark
        </div>
        <div className="space-y-1">
          <SummaryItem
            label="Alpha"
            value={formatPct(benchmark?.alpha)}
            trend={getTrend(benchmark?.alpha)}
            isLoading={isLoading}
          />
          <SummaryItem
            label="Beta"
            value={formatRatio(benchmark?.beta)}
            isLoading={isLoading}
          />
        </div>
      </div>
    </div>
  );
}

// Hero metric display for the portfolio dashboard
export function PortfolioHeroMetrics({
  totalValue,
  totalReturn,
  totalReturnPercentage,
  currency,
  isLoading,
}: {
  totalValue?: string | null;
  totalReturn?: string | null;
  totalReturnPercentage?: string | null;
  currency: string;
  isLoading?: boolean;
}) {
  if (isLoading) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-10 w-40" />
        <Skeleton className="h-5 w-24" />
      </div>
    );
  }

  const returnValue = totalReturn ? parseFloat(totalReturn) : null;
  const returnPct = totalReturnPercentage ? parseFloat(totalReturnPercentage) : null;
  const trend = getTrend(totalReturn);

  return (
    <div className="space-y-1">
      <div className="text-3xl sm:text-4xl font-bold tracking-tight">
        {totalValue ? formatCurrency(totalValue, currency) : "—"}
      </div>
      {(returnValue !== null || returnPct !== null) && (
        <div className="flex items-center gap-2">
          {trend === "up" && (
            <TrendingUp className="h-4 w-4 text-green-600 dark:text-green-500" />
          )}
          {trend === "down" && (
            <TrendingDown className="h-4 w-4 text-red-600 dark:text-red-500" />
          )}
          <span
            className={cn(
              "text-sm font-medium",
              trend === "up" && "text-green-600 dark:text-green-500",
              trend === "down" && "text-red-600 dark:text-red-500",
              trend === "neutral" && "text-muted-foreground"
            )}
          >
            {returnValue !== null && (
              <>
                {returnValue >= 0 ? "+" : ""}
                {formatCurrency(returnValue, currency)}
              </>
            )}
            {returnPct !== null && (
              <span className="ml-1">
                ({formatPercentage(returnPct)})
              </span>
            )}
          </span>
        </div>
      )}
    </div>
  );
}
