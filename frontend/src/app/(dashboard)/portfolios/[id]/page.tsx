"use client";

import { use, useMemo } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  TrendingUp,
  TrendingDown,
  AlertCircle,
  Info,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { PortfolioNav, SyncStatus } from "@/components/portfolio";
import {
  ValueChart,
  PeriodSelector,
  AllocationChart,
  QuickStats,
  type Period,
} from "@/components/charts";
import {
  usePortfolio,
  usePortfolioValuation,
  usePortfolioHistory,
  useSyncStatus,
} from "@/hooks/use-portfolios";
import { useEarliestTransactionDate } from "@/hooks/use-transactions";
import { formatCurrency, formatPercentage, formatDate } from "@/lib/utils";
import { useUIStore } from "@/stores";

// -----------------------------------------------------------------------------
// Date Helpers
// -----------------------------------------------------------------------------

function getPeriodDates(period: Period, earliestTransactionDate?: string | null): { from: string; to: string } {
  const today = new Date();
  const to = today.toISOString().split("T")[0];

  // API limit: max 20 years of history
  const twentyYearsAgo = new Date();
  twentyYearsAgo.setFullYear(twentyYearsAgo.getFullYear() - 20);
  twentyYearsAgo.setDate(twentyYearsAgo.getDate() + 1); // Add 1 day buffer
  const maxHistoryDateStr = twentyYearsAgo.toISOString().split("T")[0];

  let from: string;
  switch (period) {
    case "1M": {
      const d = new Date();
      d.setMonth(d.getMonth() - 1);
      from = d.toISOString().split("T")[0];
      break;
    }
    case "3M": {
      const d = new Date();
      d.setMonth(d.getMonth() - 3);
      from = d.toISOString().split("T")[0];
      break;
    }
    case "6M": {
      const d = new Date();
      d.setMonth(d.getMonth() - 6);
      from = d.toISOString().split("T")[0];
      break;
    }
    case "YTD":
      from = `${today.getFullYear()}-01-01`;
      break;
    case "1Y": {
      const d = new Date();
      d.setFullYear(d.getFullYear() - 1);
      from = d.toISOString().split("T")[0];
      break;
    }
    case "ALL":
    default:
      // Use earliest transaction date if available and within API limit
      if (earliestTransactionDate && earliestTransactionDate >= maxHistoryDateStr) {
        from = earliestTransactionDate;
      } else {
        from = maxHistoryDateStr;
      }
      break;
  }

  return { from, to };
}

// -----------------------------------------------------------------------------
// Metric Card Component
// -----------------------------------------------------------------------------

interface MetricCardProps {
  title: string;
  value: string;
  subValue?: string;
  trend?: "up" | "down" | "neutral";
  infoDescription: React.ReactNode;
}

function MetricCard({ title, value, subValue, trend, infoDescription }: MetricCardProps) {
  const valueColorClass = trend === "up"
    ? "text-green-600 dark:text-green-500"
    : trend === "down"
      ? "text-red-600 dark:text-red-500"
      : "";

  return (
    <Card className="py-4 gap-2">
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardDescription>{title}</CardDescription>
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <button className="text-muted-foreground hover:text-foreground transition-colors cursor-help">
                  <Info className="h-4 w-4" />
                </button>
              </TooltipTrigger>
              <TooltipContent side="top" className="max-w-[300px] p-3">
                <div className="text-xs">{infoDescription}</div>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>
      </CardHeader>
      <CardContent>
        <div className={`text-2xl font-bold ${valueColorClass}`}>{value}</div>
        {subValue && (
          <p
            className={`text-sm flex items-center gap-1 ${
              trend === "up"
                ? "text-green-600 dark:text-green-500"
                : trend === "down"
                  ? "text-red-600 dark:text-red-500"
                  : "text-muted-foreground"
            }`}
          >
            {trend === "up" && <TrendingUp className="h-4 w-4" />}
            {trend === "down" && <TrendingDown className="h-4 w-4" />}
            {subValue}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

// -----------------------------------------------------------------------------
// Portfolio Detail Page
// -----------------------------------------------------------------------------

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function PortfolioDetailPage({ params }: PageProps) {
  const { id } = use(params);
  const portfolioId = parseInt(id, 10);
  const { period, setPeriod } = useUIStore();

  const {
    data: portfolio,
    isLoading: portfolioLoading,
    error: portfolioError,
  } = usePortfolio(portfolioId);
  const {
    data: valuation,
    isLoading: valuationLoading,
  } = usePortfolioValuation(portfolioId);

  // Get earliest transaction date for "ALL" period
  const { data: earliestTransactionDate, isLoading: earliestDateLoading } = useEarliestTransactionDate(portfolioId);

  // Get date range based on selected period
  const { from: fromDate, to: toDate } = useMemo(
    () => getPeriodDates(period, earliestTransactionDate),
    [period, earliestTransactionDate]
  );

  const {
    data: history,
    isLoading: historyLoading,
  } = usePortfolioHistory(portfolioId, fromDate, toDate);

  // For "ALL" period, also consider earliest date loading state
  const valueChartLoading = historyLoading || (period === "ALL" && earliestDateLoading);

  const { data: syncStatus } = useSyncStatus(portfolioId);

  if (portfolioLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-48" />
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {[1, 2, 3, 4].map((i) => (
            <Card key={i}>
              <CardHeader className="pb-2">
                <Skeleton className="h-4 w-20" />
              </CardHeader>
              <CardContent>
                <Skeleton className="h-8 w-24" />
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    );
  }

  if (portfolioError || !portfolio) {
    return (
      <div className="space-y-6">
        <Button variant="ghost" asChild className="-ml-4">
          <Link href="/portfolios">
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back to portfolios
          </Link>
        </Button>
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Error</AlertTitle>
          <AlertDescription>
            {portfolioError instanceof Error
              ? portfolioError.message
              : "Portfolio not found"}
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  const summary = valuation?.summary;
  const holdings = valuation?.holdings || [];
  const currency = portfolio.currency;

  // Calculate trends
  const getTrend = (value: string | null | undefined): "up" | "down" | "neutral" => {
    if (!value) return "neutral";
    const num = parseFloat(value);
    if (num > 0) return "up";
    if (num < 0) return "down";
    return "neutral";
  };

  // Format P/L value with +/- sign
  const formatPnlValue = (value: number | null, curr: string): string => {
    if (value === null) return "—";
    const sign = value > 0 ? "+" : value < 0 ? "-" : "";
    return `${sign}${formatCurrency(Math.abs(value), curr)}`;
  };

  // Parse summary values for QuickStats
  const totalPnl = summary?.total_pnl ? parseFloat(summary.total_pnl) : null;
  const totalPnlPct = summary?.total_pnl_percentage
    ? parseFloat(summary.total_pnl_percentage)
    : null;
  const unrealizedPnl = summary?.total_unrealized_pnl
    ? parseFloat(summary.total_unrealized_pnl)
    : null;
  const realizedPnl = summary?.total_realized_pnl
    ? parseFloat(summary.total_realized_pnl)
    : null;
  const dayChange = summary?.day_change ? parseFloat(summary.day_change) : null;
  const dayChangePercentage = summary?.day_change_percentage
    ? parseFloat(summary.day_change_percentage)
    : null;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" asChild className="-ml-2">
            <Link href="/portfolios">
              <ArrowLeft className="h-4 w-4" />
            </Link>
          </Button>
          <div>
            <h1 className="text-2xl font-bold tracking-tight">
              {portfolio.name}
            </h1>
            <p className="text-sm text-muted-foreground">
              Base currency: {currency}
            </p>
          </div>
        </div>
        <SyncStatus portfolioId={portfolioId} />
      </div>

      {/* Navigation */}
      <PortfolioNav portfolioId={portfolioId} />

      {/* Warnings */}
      {valuation?.warnings && valuation.warnings.length > 0 && (
        <Alert>
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Warnings</AlertTitle>
          <AlertDescription>
            <ul className="list-disc list-inside">
              {valuation.warnings.map((warning, i) => (
                <li key={i}>{warning}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}

      {/* Quick Stats Row */}
      {summary && (
        <QuickStats
          currency={currency}
          todayChange={dayChange}
          todayChangePercentage={dayChangePercentage}
          totalReturn={totalPnl}
          totalReturnPercentage={totalPnlPct}
          lastUpdated={
            syncStatus?.completed_at
              ? formatDate(syncStatus.completed_at, {
                  month: "short",
                  day: "numeric",
                  hour: "numeric",
                  minute: "numeric",
                })
              : valuation?.valuation_date
                ? formatDate(valuation.valuation_date, {
                    month: "short",
                    day: "numeric",
                  })
                : undefined
          }
          isLoading={valuationLoading}
        />
      )}

      {/* Metrics */}
      {valuationLoading ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {[1, 2, 3, 4].map((i) => (
            <Card key={i}>
              <CardHeader className="pb-2">
                <Skeleton className="h-4 w-20" />
              </CardHeader>
              <CardContent>
                <Skeleton className="h-8 w-24" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : summary ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          <MetricCard
            title="Current Value"
            value={formatCurrency(summary.total_equity ?? summary.total_value, currency)}
            infoDescription="The estimated amount you would receive if you sold everything today. It represents the total market value of your holdings, equal to your Net Invested capital plus your Total P/L."
          />
          <MetricCard
            title="Total Net Invested"
            value={formatCurrency(summary.total_net_invested, currency)}
            infoDescription="The total cash you contributed from your bank account. Calculated as Total Deposits/Buys minus Total Withdrawals/Sales. This is your principal capital and does not include reinvested profits from previous trades."
          />
          <MetricCard
            title="Unrealized P/L"
            value={formatPnlValue(unrealizedPnl, currency)}
            subValue={
              unrealizedPnl !== null && parseFloat(summary.total_cost_basis) > 0
                ? formatPercentage(unrealizedPnl / parseFloat(summary.total_cost_basis))
                : undefined
            }
            trend={getTrend(summary.total_unrealized_pnl)}
            infoDescription={
              <p>The floating "paper" profit or loss on your open positions. This value fluctuates with the market price of your current holdings and only becomes permanent (realized) when you sell them.</p>
            }
          />
          <MetricCard
            title="Realized P/L"
            value={formatPnlValue(realizedPnl, currency)}
            trend={getTrend(summary.total_realized_pnl)}
            infoDescription={
              <p>The total profit or loss from assets you have already sold. These gains or losses are "locked in" and are no longer exposed to market risk.</p>
            }
          />
        </div>
      ) : (
        <Alert>
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>No valuation data</AlertTitle>
          <AlertDescription>
            Add transactions and sync market data to see your portfolio valuation.
          </AlertDescription>
        </Alert>
      )}

      {/* Charts Section */}
      <div className="grid gap-6 lg:grid-cols-3">
        {/* Value Chart (spans 2 columns on large screens) */}
        <div className="lg:col-span-2 space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <h2 className="text-lg font-semibold">Portfolio Performance</h2>
            <PeriodSelector value={period} onChange={setPeriod} />
          </div>
          <ValueChart
            data={history?.data || []}
            currency={currency}
            isLoading={valueChartLoading}
            title=""
            showCostBasis
            period={period}
          />
        </div>

        {/* Allocation Chart */}
        <div>
          <AllocationChart
            holdings={holdings}
            currency={currency}
            groupBy="asset_class"
            isLoading={valuationLoading}
            title="Allocation"
          />
        </div>
      </div>
    </div>
  );
}
