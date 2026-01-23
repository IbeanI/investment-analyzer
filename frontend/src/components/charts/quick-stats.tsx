"use client";

import { TrendingUp, TrendingDown, Minus, Clock, Info } from "lucide-react";
import { cn, formatCurrency, formatPercentage } from "@/lib/utils";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface QuickStatsProps {
  currency: string;
  todayChange?: number | null;
  todayChangePercentage?: number | null;
  totalReturn?: number | null;
  totalReturnPercentage?: number | null;
  unrealizedPnl?: number | null;
  unrealizedPnlPercentage?: number | null;
  lastUpdated?: string | null;
  isLoading?: boolean;
}

interface StatItemProps {
  label: string;
  value: string;
  percentage?: string;
  trend: "up" | "down" | "neutral";
  isLoading?: boolean;
  infoDescription?: React.ReactNode;
}

function StatItem({ label, value, percentage, trend, isLoading, infoDescription }: StatItemProps) {
  if (isLoading) {
    return (
      <div className="flex flex-col gap-1">
        <span className="text-xs text-muted-foreground">{label}</span>
        <div className="h-5 w-16 bg-muted animate-pulse rounded" />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex items-center gap-1">
        <span className="text-xs text-muted-foreground">{label}</span>
        {infoDescription && (
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <button className="text-muted-foreground hover:text-foreground transition-colors cursor-help">
                  <Info className="h-3 w-3" />
                </button>
              </TooltipTrigger>
              <TooltipContent side="top" className="max-w-[300px] p-3">
                <div className="text-xs">{infoDescription}</div>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        )}
      </div>
      <div className="flex items-center gap-1.5">
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
            "text-sm font-medium",
            trend === "up" && "text-green-600 dark:text-green-500",
            trend === "down" && "text-red-600 dark:text-red-500",
            trend === "neutral" && "text-muted-foreground"
          )}
        >
          {value}
        </span>
        {percentage && (
          <span
            className={cn(
              "text-xs",
              trend === "up" && "text-green-600/80 dark:text-green-500/80",
              trend === "down" && "text-red-600/80 dark:text-red-500/80",
              trend === "neutral" && "text-muted-foreground"
            )}
          >
            ({percentage})
          </span>
        )}
      </div>
    </div>
  );
}

function getTrend(value: number | null | undefined): "up" | "down" | "neutral" {
  if (value === null || value === undefined || value === 0) return "neutral";
  return value > 0 ? "up" : "down";
}

export function QuickStats({
  currency,
  todayChange,
  todayChangePercentage,
  totalReturn,
  totalReturnPercentage,
  unrealizedPnl,
  unrealizedPnlPercentage,
  lastUpdated,
  isLoading,
}: QuickStatsProps) {
  const formatValue = (value: number | null | undefined) => {
    if (value === null || value === undefined) return "—";
    const sign = value > 0 ? "+" : value < 0 ? "-" : "";
    return `${sign}${formatCurrency(Math.abs(value), currency)}`;
  };

  const formatPct = (value: number | null | undefined) => {
    if (value === null || value === undefined) return undefined;
    return formatPercentage(value);
  };

  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-3 py-3 px-4 bg-muted/30 rounded-lg border">
      <StatItem
        label="Daily P/L"
        value={formatValue(todayChange)}
        percentage={formatPct(todayChangePercentage)}
        trend={getTrend(todayChange)}
        isLoading={isLoading}
      />
      <div className="hidden sm:block h-8 w-px bg-border" />
      <StatItem
        label="Total P/L"
        value={formatValue(totalReturn)}
        percentage={formatPct(totalReturnPercentage)}
        trend={getTrend(totalReturn)}
        isLoading={isLoading}
        infoDescription={
          <>
            <p className="font-medium mb-1">Total Profit/Loss</p>
            <p>The cumulative financial outcome of your entire portfolio history. This value combines your <strong>Realized Profit/Loss</strong> (profits you have already secured) and your <strong>Unrealized Profit/Loss</strong> (paper profits on assets you still hold).</p>
          </>
        }
      />
      {lastUpdated && (
        <>
          <div className="hidden lg:block h-8 w-px bg-border" />
          <div className="hidden lg:flex items-center gap-1.5 text-xs text-muted-foreground">
            <Clock className="h-3 w-3" />
            <span>Updated {lastUpdated}</span>
          </div>
        </>
      )}
    </div>
  );
}

// Compact version for mobile
export function QuickStatsCompact({
  currency,
  todayChange,
  todayChangePercentage,
  totalReturn,
  totalReturnPercentage,
  isLoading,
}: Omit<QuickStatsProps, "unrealizedPnl" | "unrealizedPnlPercentage" | "lastUpdated">) {
  const formatValue = (value: number | null | undefined) => {
    if (value === null || value === undefined) return "—";
    const sign = value > 0 ? "+" : value < 0 ? "-" : "";
    return `${sign}${formatCurrency(Math.abs(value), currency)}`;
  };

  const formatPct = (value: number | null | undefined) => {
    if (value === null || value === undefined) return undefined;
    return formatPercentage(value);
  };

  return (
    <div className="flex items-center justify-between gap-4 py-2">
      <StatItem
        label="Daily P/L"
        value={formatValue(todayChange)}
        percentage={formatPct(todayChangePercentage)}
        trend={getTrend(todayChange)}
        isLoading={isLoading}
      />
      <StatItem
        label="Total P/L"
        value={formatValue(totalReturn)}
        percentage={formatPct(totalReturnPercentage)}
        trend={getTrend(totalReturn)}
        isLoading={isLoading}
        infoDescription={
          <>
            <p className="font-medium mb-1">Total Profit/Loss</p>
            <p>The cumulative financial outcome of your entire portfolio history. This value combines your <strong>Realized Profit/Loss</strong> (profits you have already secured) and your <strong>Unrealized Profit/Loss</strong> (paper profits on assets you still hold).</p>
          </>
        }
      />
    </div>
  );
}
