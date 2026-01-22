"use client";

import { use, useMemo, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  TrendingUp,
  BarChart3,
  Shield,
  Target,
  Info,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
} from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  PeriodSelector,
  DrawdownChart,
  BenchmarkChart,
  type Period,
} from "@/components/charts";
import { MetricExplainer } from "@/components/analytics";
import {
  usePortfolio,
  usePortfolioAnalytics,
  usePortfolioHistory,
} from "@/hooks/use-portfolios";
import { formatPercentage, formatCurrency, formatDate, cn } from "@/lib/utils";

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
  value: string | null;
  description: string;
  trend?: "up" | "down" | "neutral";
  isLoading?: boolean;
}

function MetricCard({
  title,
  value,
  description,
  trend,
  isLoading,
}: MetricCardProps) {
  if (isLoading) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-4 w-4 rounded-full" />
          </div>
        </CardHeader>
        <CardContent>
          <Skeleton className="h-8 w-20" />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardDescription>{title}</CardDescription>
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <Info className="h-4 w-4 text-muted-foreground cursor-help" />
              </TooltipTrigger>
              <TooltipContent side="top" className="max-w-xs">
                <p className="text-sm">{description}</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>
      </CardHeader>
      <CardContent>
        <div
          className={cn(
            "text-2xl font-bold",
            trend === "up" && "text-green-600 dark:text-green-500",
            trend === "down" && "text-red-600 dark:text-red-500"
          )}
        >
          {value ?? "—"}
        </div>
      </CardContent>
    </Card>
  );
}

// -----------------------------------------------------------------------------
// Analytics Page
// -----------------------------------------------------------------------------

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function AnalyticsPage({ params }: PageProps) {
  const { id } = use(params);
  const portfolioId = parseInt(id, 10);
  const [period, setPeriod] = useState<Period>("1Y");
  const [activeTab, setActiveTab] = useState("performance");

  const { data: portfolio, isLoading: portfolioLoading } =
    usePortfolio(portfolioId);

  const { from: fromDate, to: toDate } = useMemo(
    () => getPeriodDates(period),
    [period]
  );

  const { data: analytics, isLoading: analyticsLoading } =
    usePortfolioAnalytics(portfolioId, fromDate, toDate);

  const { data: history, isLoading: historyLoading } =
    usePortfolioHistory(portfolioId, fromDate, toDate);

  const isLoading = portfolioLoading || analyticsLoading;

  // Helper to format metric values
  const formatMetric = (
    value: string | number | null | undefined,
    type: "percentage" | "ratio" | "number" | "currency" = "percentage"
  ): string | null => {
    if (value === null || value === undefined) return null;
    const num = typeof value === "string" ? parseFloat(value) : value;
    if (isNaN(num)) return null;

    switch (type) {
      case "percentage":
        return formatPercentage(num);
      case "ratio":
        return num.toFixed(2);
      case "number":
        return num.toLocaleString();
      case "currency":
        return formatCurrency(num, analytics?.portfolio_currency || "EUR");
      default:
        return String(num);
    }
  };

  // Get trend direction for a metric
  const getTrend = (
    value: string | number | null | undefined
  ): "up" | "down" | "neutral" => {
    if (value === null || value === undefined) return "neutral";
    const num = typeof value === "string" ? parseFloat(value) : value;
    if (isNaN(num) || num === 0) return "neutral";
    return num > 0 ? "up" : "down";
  };

  const performance = analytics?.performance;
  const risk = analytics?.risk;
  const benchmark = analytics?.benchmark;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" asChild className="-ml-2">
            <Link href={`/portfolios/${portfolioId}`}>
              <ArrowLeft className="h-4 w-4" />
            </Link>
          </Button>
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Analytics</h1>
            <p className="text-sm text-muted-foreground">
              {portfolio?.name || "Loading..."}
            </p>
          </div>
        </div>
        <PeriodSelector value={period} onChange={setPeriod} />
      </div>

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="grid w-full grid-cols-3">
          <TabsTrigger value="performance" className="flex items-center gap-2">
            <TrendingUp className="h-4 w-4" />
            <span className="hidden sm:inline">Performance</span>
          </TabsTrigger>
          <TabsTrigger value="risk" className="flex items-center gap-2">
            <Shield className="h-4 w-4" />
            <span className="hidden sm:inline">Risk</span>
          </TabsTrigger>
          <TabsTrigger value="benchmark" className="flex items-center gap-2">
            <Target className="h-4 w-4" />
            <span className="hidden sm:inline">Benchmark</span>
          </TabsTrigger>
        </TabsList>

        {/* Performance Tab */}
        <TabsContent value="performance" className="space-y-6">
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            <MetricCard
              title="Simple Return"
              value={formatMetric(performance?.simple_return)}
              description="Total percentage gain or loss from your initial investment."
              trend={getTrend(performance?.simple_return)}
              isLoading={isLoading}
            />
            <MetricCard
              title="TWR"
              value={formatMetric(performance?.twr)}
              description="Time-Weighted Return measures investment performance excluding the impact of deposits and withdrawals."
              trend={getTrend(performance?.twr)}
              isLoading={isLoading}
            />
            <MetricCard
              title="XIRR"
              value={formatMetric(performance?.xirr)}
              description="Extended Internal Rate of Return accounts for the timing and size of all cash flows."
              trend={getTrend(performance?.xirr)}
              isLoading={isLoading}
            />
            <MetricCard
              title="CAGR"
              value={formatMetric(performance?.cagr)}
              description="Compound Annual Growth Rate shows the smoothed annual return over time."
              trend={getTrend(performance?.cagr)}
              isLoading={isLoading}
            />
          </div>

          {/* Additional Performance Metrics */}
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            <MetricCard
              title="Total Gain"
              value={formatMetric(performance?.total_gain, "currency")}
              description="Total monetary gain or loss in portfolio currency."
              trend={getTrend(performance?.total_gain)}
              isLoading={isLoading}
            />
            <MetricCard
              title="Beginning Value"
              value={formatMetric(performance?.start_value, "currency")}
              description={`Portfolio value at the beginning of the period (${formatDate(fromDate)}).`}
              isLoading={isLoading}
            />
            <MetricCard
              title="Ending Value"
              value={formatMetric(performance?.end_value, "currency")}
              description={`Portfolio value at the end of the period (${formatDate(toDate)}).`}
              isLoading={isLoading}
            />
            <MetricCard
              title="Net Invested"
              value={formatMetric(performance?.net_invested, "currency")}
              description="Total deposits minus withdrawals during the period."
              isLoading={isLoading}
            />
          </div>

          {/* Metric Explainer */}
          <MetricExplainer category="performance" />

          {!isLoading && !performance && (
            <Alert>
              <BarChart3 className="h-4 w-4" />
              <AlertTitle>No performance data</AlertTitle>
              <AlertDescription>
                Performance metrics will appear once you have enough transaction
                history.
              </AlertDescription>
            </Alert>
          )}
        </TabsContent>

        {/* Risk Tab */}
        <TabsContent value="risk" className="space-y-6">
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            <MetricCard
              title="Volatility"
              value={formatMetric(risk?.volatility_annualized)}
              description="Annualized standard deviation of returns. Higher values indicate more price fluctuation."
              isLoading={isLoading}
            />
            <MetricCard
              title="Sharpe Ratio"
              value={formatMetric(risk?.sharpe_ratio, "ratio")}
              description="Risk-adjusted return. Above 1 is good, above 2 is excellent."
              trend={
                risk?.sharpe_ratio
                  ? parseFloat(String(risk.sharpe_ratio)) >= 1
                    ? "up"
                    : "down"
                  : "neutral"
              }
              isLoading={isLoading}
            />
            <MetricCard
              title="Sortino Ratio"
              value={formatMetric(risk?.sortino_ratio, "ratio")}
              description="Like Sharpe, but only penalizes downside volatility. Higher is better."
              trend={
                risk?.sortino_ratio
                  ? parseFloat(String(risk.sortino_ratio)) >= 1
                    ? "up"
                    : "down"
                  : "neutral"
              }
              isLoading={isLoading}
            />
            <MetricCard
              title="Max Drawdown"
              value={formatMetric(risk?.max_drawdown)}
              description="The largest peak-to-trough decline in portfolio value."
              trend="down"
              isLoading={isLoading}
            />
          </div>

          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            <MetricCard
              title="VaR (95%)"
              value={formatMetric(risk?.var_95)}
              description="Value at Risk: The maximum expected loss over a day with 95% confidence."
              isLoading={isLoading}
            />
            <MetricCard
              title="CVaR (95%)"
              value={formatMetric(risk?.cvar_95)}
              description="Conditional VaR: The expected loss if VaR is exceeded."
              isLoading={isLoading}
            />
            <MetricCard
              title="Win Rate"
              value={formatMetric(risk?.win_rate)}
              description="Percentage of days with positive returns."
              trend={
                risk?.win_rate
                  ? parseFloat(String(risk.win_rate)) >= 0.5
                    ? "up"
                    : "down"
                  : "neutral"
              }
              isLoading={isLoading}
            />
            <MetricCard
              title="Best Day"
              value={formatMetric(risk?.best_day)}
              description="The highest single-day return in the selected period."
              trend="up"
              isLoading={isLoading}
            />
          </div>

          {/* Drawdown Chart */}
          <DrawdownChart
            data={history?.data || []}
            maxDrawdown={risk?.max_drawdown}
            maxDrawdownStart={risk?.max_drawdown_start}
            maxDrawdownEnd={risk?.max_drawdown_end}
            currentDrawdown={risk?.current_drawdown}
            drawdownPeriods={risk?.drawdown_periods}
            isLoading={historyLoading || analyticsLoading}
          />

          {/* Metric Explainer */}
          <MetricExplainer category="risk" />

          {!isLoading && !risk && (
            <Alert>
              <Shield className="h-4 w-4" />
              <AlertTitle>No risk data</AlertTitle>
              <AlertDescription>
                Risk metrics will appear once you have enough price history.
              </AlertDescription>
            </Alert>
          )}
        </TabsContent>

        {/* Benchmark Tab */}
        <TabsContent value="benchmark" className="space-y-6">
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            <MetricCard
              title="Alpha"
              value={formatMetric(benchmark?.alpha)}
              description="Excess return compared to the benchmark. Positive alpha means outperformance."
              trend={getTrend(benchmark?.alpha)}
              isLoading={isLoading}
            />
            <MetricCard
              title="Beta"
              value={formatMetric(benchmark?.beta, "ratio")}
              description="Sensitivity to market movements. Beta > 1 means more volatile than the market."
              isLoading={isLoading}
            />
            <MetricCard
              title="Correlation"
              value={formatMetric(benchmark?.correlation, "ratio")}
              description="How closely your portfolio moves with the benchmark. 1 = perfect correlation."
              isLoading={isLoading}
            />
            <MetricCard
              title="Tracking Error"
              value={formatMetric(benchmark?.tracking_error)}
              description="Standard deviation of the difference between portfolio and benchmark returns."
              isLoading={isLoading}
            />
          </div>

          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            <MetricCard
              title="Portfolio Return"
              value={formatMetric(benchmark?.portfolio_return)}
              description="Your portfolio's return over the selected period."
              trend={getTrend(benchmark?.portfolio_return)}
              isLoading={isLoading}
            />
            <MetricCard
              title="Benchmark Return"
              value={formatMetric(benchmark?.benchmark_return)}
              description="The benchmark's return over the selected period."
              trend={getTrend(benchmark?.benchmark_return)}
              isLoading={isLoading}
            />
            <MetricCard
              title="Excess Return"
              value={formatMetric(benchmark?.excess_return)}
              description="The difference between your portfolio return and the benchmark."
              trend={getTrend(benchmark?.excess_return)}
              isLoading={isLoading}
            />
            <MetricCard
              title="Information Ratio"
              value={formatMetric(benchmark?.information_ratio, "ratio")}
              description="Excess return divided by tracking error. Higher is better."
              trend={
                benchmark?.information_ratio
                  ? parseFloat(String(benchmark.information_ratio)) > 0
                    ? "up"
                    : "down"
                  : "neutral"
              }
              isLoading={isLoading}
            />
          </div>

          {/* Benchmark Comparison Chart */}
          <BenchmarkChart
            portfolioData={history?.data || []}
            benchmarkName={benchmark?.benchmark_name || "S&P 500"}
            portfolioReturn={benchmark?.portfolio_return}
            benchmarkReturn={benchmark?.benchmark_return}
            alpha={benchmark?.alpha}
            isLoading={historyLoading || analyticsLoading}
          />

          {/* Metric Explainer */}
          <MetricExplainer category="benchmark" />

          {!isLoading && !benchmark && (
            <Alert>
              <Target className="h-4 w-4" />
              <AlertTitle>No benchmark data</AlertTitle>
              <AlertDescription>
                Benchmark comparison will appear once market data is synced.
              </AlertDescription>
            </Alert>
          )}
        </TabsContent>
      </Tabs>

      {/* Back to Portfolio */}
      <div className="flex gap-2">
        <Button variant="outline" asChild>
          <Link href={`/portfolios/${portfolioId}`}>Back to Portfolio</Link>
        </Button>
      </div>
    </div>
  );
}
