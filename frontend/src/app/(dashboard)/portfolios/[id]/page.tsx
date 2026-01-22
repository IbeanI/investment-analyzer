"use client";

import { use, useMemo, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  TrendingUp,
  TrendingDown,
  AlertCircle,
  Plus,
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
import { HoldingsTable, SyncStatus } from "@/components/portfolio";
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
} from "@/hooks/use-portfolios";
import { formatCurrency, formatPercentage, formatDate } from "@/lib/utils";

// -----------------------------------------------------------------------------
// Date Helpers
// -----------------------------------------------------------------------------

function getPeriodDates(period: Period): { from: string; to: string } {
  const now = new Date();
  const to = now.toISOString().split("T")[0];

  let from: Date;
  switch (period) {
    case "1M":
      from = new Date(now.setMonth(now.getMonth() - 1));
      break;
    case "3M":
      from = new Date(now.setMonth(now.getMonth() - 3));
      break;
    case "6M":
      from = new Date(now.setMonth(now.getMonth() - 6));
      break;
    case "YTD":
      from = new Date(now.getFullYear(), 0, 1);
      break;
    case "1Y":
      from = new Date(now.setFullYear(now.getFullYear() - 1));
      break;
    case "ALL":
    default:
      // 10 years back as "ALL"
      from = new Date(now.setFullYear(now.getFullYear() - 10));
      break;
  }

  return {
    from: from.toISOString().split("T")[0],
    to,
  };
}

// -----------------------------------------------------------------------------
// Metric Card Component
// -----------------------------------------------------------------------------

interface MetricCardProps {
  title: string;
  value: string;
  subValue?: string;
  trend?: "up" | "down" | "neutral";
}

function MetricCard({ title, value, subValue, trend }: MetricCardProps) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardDescription>{title}</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-bold">{value}</div>
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
  const [period, setPeriod] = useState<Period>("1Y");

  const {
    data: portfolio,
    isLoading: portfolioLoading,
    error: portfolioError,
  } = usePortfolio(portfolioId);
  const {
    data: valuation,
    isLoading: valuationLoading,
  } = usePortfolioValuation(portfolioId);

  // Get date range based on selected period
  const { from: fromDate, to: toDate } = useMemo(
    () => getPeriodDates(period),
    [period]
  );

  const {
    data: history,
    isLoading: historyLoading,
  } = usePortfolioHistory(portfolioId, fromDate, toDate);

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

  // Parse summary values for QuickStats
  const totalPnl = summary?.total_pnl ? parseFloat(summary.total_pnl) : null;
  const totalPnlPct = summary?.total_pnl_percentage
    ? parseFloat(summary.total_pnl_percentage)
    : null;
  const unrealizedPnl = summary?.total_unrealized_pnl
    ? parseFloat(summary.total_unrealized_pnl)
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
          totalReturn={totalPnl}
          totalReturnPercentage={totalPnlPct}
          unrealizedPnl={unrealizedPnl}
          lastUpdated={
            valuation?.valuation_date
              ? formatDate(valuation.valuation_date, {
                  month: "short",
                  day: "numeric",
                  hour: "numeric",
                  minute: "numeric",
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
            title="Total Value"
            value={formatCurrency(summary.total_value, currency)}
          />
          <MetricCard
            title="Cost Basis"
            value={formatCurrency(summary.total_cost_basis, currency)}
          />
          <MetricCard
            title="Total P&L"
            value={formatCurrency(summary.total_pnl, currency)}
            subValue={
              summary.total_pnl_percentage
                ? formatPercentage(summary.total_pnl_percentage)
                : undefined
            }
            trend={getTrend(summary.total_pnl)}
          />
          <MetricCard
            title="Unrealized P&L"
            value={formatCurrency(summary.total_unrealized_pnl, currency)}
            trend={getTrend(summary.total_unrealized_pnl)}
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
            isLoading={historyLoading}
            title=""
            showCostBasis
          />
        </div>

        {/* Allocation Chart */}
        <div>
          <AllocationChart
            holdings={holdings}
            currency={currency}
            groupBy="ticker"
            isLoading={valuationLoading}
            title="Allocation"
          />
        </div>
      </div>

      {/* Holdings */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle>Holdings</CardTitle>
            <CardDescription>
              {valuation?.valuation_date
                ? `As of ${formatDate(valuation.valuation_date)}`
                : "Add transactions and sync to see holdings"}
            </CardDescription>
          </div>
          <Button size="sm" asChild>
            <Link href={`/portfolios/${portfolioId}/transactions`}>
              <Plus className="mr-2 h-4 w-4" />
              Add
            </Link>
          </Button>
        </CardHeader>
        <CardContent>
          <HoldingsTable holdings={holdings} currency={currency} />
        </CardContent>
      </Card>

      {/* Quick Actions */}
      <div className="flex flex-wrap gap-2">
        <Button asChild>
          <Link href={`/portfolios/${portfolioId}/transactions`}>
            Transactions
          </Link>
        </Button>
        <Button variant="outline" asChild>
          <Link href={`/portfolios/${portfolioId}/analytics`}>Analytics</Link>
        </Button>
        <Button variant="outline" asChild>
          <Link href={`/portfolios/${portfolioId}/settings`}>Settings</Link>
        </Button>
      </div>
    </div>
  );
}
