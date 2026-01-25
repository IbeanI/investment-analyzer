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
  ChevronDown,
  ChevronUp,
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
import { PortfolioNav } from "@/components/portfolio";
import {
  usePortfolio,
  usePortfolioAnalytics,
  usePortfolioHistory,
} from "@/hooks/use-portfolios";
import { useEarliestTransactionDate } from "@/hooks/use-transactions";
import { formatPercentage, formatCurrency, formatDate, cn } from "@/lib/utils";
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
// Metric Card Components
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

interface HeroMetricCardProps {
  title: string;
  subtitle: string;
  value: string | null;
  description: string;
  trend?: "up" | "down" | "neutral";
  isLoading?: boolean;
}

function HeroMetricCard({
  title,
  subtitle,
  value,
  description,
  trend,
  isLoading,
}: HeroMetricCardProps) {
  if (isLoading) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-4 w-4 rounded-full" />
          </div>
        </CardHeader>
        <CardContent className="space-y-1">
          <Skeleton className="h-9 w-24" />
          <Skeleton className="h-3 w-20" />
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
      <CardContent className="space-y-1">
        <div
          className={cn(
            "text-3xl font-bold",
            trend === "up" && "text-green-600 dark:text-green-500",
            trend === "down" && "text-red-600 dark:text-red-500"
          )}
        >
          {value ?? "—"}
        </div>
        <p className="text-xs text-muted-foreground">{subtitle}</p>
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
  const { period, setPeriod } = useUIStore();
  const [activeTab, setActiveTab] = useState("performance");
  const [syntheticWarningExpanded, setSyntheticWarningExpanded] = useState(false);

  const { data: portfolio, isLoading: portfolioLoading } =
    usePortfolio(portfolioId);

  // Get earliest transaction date for "ALL" period
  const { data: earliestTransactionDate, isLoading: earliestDateLoading } = useEarliestTransactionDate(portfolioId);

  const { from: fromDate, to: toDate } = useMemo(
    () => getPeriodDates(period, earliestTransactionDate),
    [period, earliestTransactionDate]
  );

  const { data: analytics, isLoading: analyticsLoading } =
    usePortfolioAnalytics(portfolioId, fromDate, toDate);

  const { data: history, isLoading: historyLoading } =
    usePortfolioHistory(portfolioId, fromDate, toDate);

  const isLoading = portfolioLoading || analyticsLoading;

  // For "ALL" period, also consider earliest date loading state
  const chartLoading = historyLoading || (period === "ALL" && earliestDateLoading);

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

  // Format P/L currency value with +/- sign (for consistency with other pages)
  const formatPnlCurrency = (
    value: string | number | null | undefined
  ): string | null => {
    if (value === null || value === undefined) return null;
    const num = typeof value === "string" ? parseFloat(value) : value;
    if (isNaN(num)) return null;
    const sign = num > 0 ? "+" : num < 0 ? "-" : "";
    return `${sign}${formatCurrency(Math.abs(num), analytics?.portfolio_currency || "EUR")}`;
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
            <h1 className="text-2xl font-bold tracking-tight">
              {portfolio?.name || "Loading..."}
            </h1>
            <p className="text-sm text-muted-foreground">Analytics</p>
          </div>
        </div>
        <PeriodSelector value={period} onChange={setPeriod} />
      </div>

      {/* Navigation */}
      <PortfolioNav portfolioId={portfolioId} />

      {/* Synthetic Data Disclaimer */}
      {analytics?.has_synthetic_data && analytics?.synthetic_details && (() => {
        const syntheticAssets = Object.entries(analytics.synthetic_details);
        const hasProxyBackcast = syntheticAssets.some(([, d]) => d.synthetic_method === "proxy_backcast");
        const hasCostCarry = syntheticAssets.some(([, d]) => d.synthetic_method === "cost_carry");

        return (
          <Alert variant="default" className="border-amber-200 bg-amber-50 dark:border-amber-900 dark:bg-amber-950">
            <Info className="h-4 w-4 text-amber-600 dark:text-amber-400" />
            <div className="flex-1">
              <div
                className="flex items-center justify-between cursor-pointer"
                onClick={() => setSyntheticWarningExpanded(!syntheticWarningExpanded)}
              >
                <AlertTitle className="text-amber-800 dark:text-amber-200 mb-0">
                  Modeled Historical Data
                </AlertTitle>
                <button
                  type="button"
                  className="text-amber-600 dark:text-amber-400 hover:text-amber-800 dark:hover:text-amber-200 flex items-center gap-1 text-xs"
                >
                  {syntheticWarningExpanded ? (
                    <>
                      Show less
                      <ChevronUp className="h-4 w-4" />
                    </>
                  ) : (
                    <>
                      Show more
                      <ChevronDown className="h-4 w-4" />
                    </>
                  )}
                </button>
              </div>

              {syntheticWarningExpanded && (
                <AlertDescription className="text-amber-700 dark:text-amber-300 mt-2">
                  <p className="mb-3">
                    Some historical performance data is estimated due to limited market data availability:
                  </p>

                  {/* Table display */}
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-amber-300 dark:border-amber-700">
                          <th className="text-left py-2 pr-4 font-semibold">Asset</th>
                          <th className="text-left py-2 pr-4 font-semibold">Method</th>
                          <th className="text-left py-2 pr-4 font-semibold">Date Range</th>
                          <th className="text-left py-2 pr-4 font-semibold">Proxy Used</th>
                          <th className="text-right py-2 font-semibold">Days</th>
                        </tr>
                      </thead>
                      <tbody>
                        {syntheticAssets.map(([ticker, detail]) => (
                          <tr key={ticker} className="border-b border-amber-200 dark:border-amber-800 last:border-0">
                            <td className="py-2 pr-4 font-medium">{ticker}</td>
                            <td className="py-2 pr-4">
                              {detail.synthetic_method === "proxy_backcast" ? "Proxy Backcast" : "Cost Carry"}
                            </td>
                            <td className="py-2 pr-4">
                              {formatDate(detail.first_synthetic_date)} – {formatDate(detail.last_synthetic_date)}
                            </td>
                            <td className="py-2 pr-4">
                              {detail.proxy_ticker || "—"}
                            </td>
                            <td className="py-2 text-right">{detail.synthetic_days}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  <p className="mt-3 text-xs">
                    {hasProxyBackcast && (
                      <>
                        <strong>Proxy backcasting:</strong> Prices scaled from a correlated asset based on the ratio at the first available real price.{" "}
                      </>
                    )}
                    {hasCostCarry && (
                      <>
                        <strong>Cost carry:</strong> Asset valued at purchase price when no market data or proxy is available.{" "}
                      </>
                    )}
                    Actual historical performance may have differed.
                  </p>
                </AlertDescription>
              )}
            </div>
          </Alert>
        );
      })()}

      {/* Analytics Tabs */}
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
        <TabsContent value="performance" className="space-y-4">
          {/* Row 1: Bottom Line (Context) */}
          <div className="grid gap-4 grid-cols-3">
            <MetricCard
              title="Total Value"
              value={formatMetric(performance?.end_value, "currency")}
              description="Liquidation value of your portfolio. The amount you would receive if you sold all holdings today."
              isLoading={isLoading}
            />
            <MetricCard
              title="Net Invested"
              value={formatMetric(performance?.net_invested, "currency")}
              description="Your total principal capital. Total Deposits/Buys minus Total Withdrawals/Sales."
              isLoading={isLoading}
            />
            <MetricCard
              title="Total P/L"
              value={formatPnlCurrency(performance?.total_gain)}
              description="Total profit or loss since inception. The financial growth relative to your Net Invested capital."
              trend={getTrend(performance?.total_gain)}
              isLoading={isLoading}
            />
          </div>

          {/* Row 2: Hero Section (Institutional Performance) */}
          <div className="grid gap-4 grid-cols-3">
            <HeroMetricCard
              title="TWR (Cumulative)"
              subtitle="Strategy Growth"
              value={formatMetric(performance?.twr)}
              description="Strategy performance for this period. Measures how your assets performed, ignoring deposit/withdrawal timing."
              trend={getTrend(performance?.twr)}
              isLoading={isLoading}
            />
            <HeroMetricCard
              title="TWR Annualized"
              subtitle="Yearly Avg"
              value={formatMetric(performance?.twr_annualized)}
              description="Compound annual growth rate. What your TWR would look like if maintained for a full year."
              trend={getTrend(performance?.twr_annualized)}
              isLoading={isLoading}
            />
            <HeroMetricCard
              title="XIRR"
              subtitle="Personal ROI"
              value={formatMetric(performance?.xirr)}
              description="Your personal annualized return. Accounts for the timing of every deposit and withdrawal."
              trend={getTrend(performance?.xirr)}
              isLoading={isLoading}
            />
          </div>

          {/* Row 3: Secondary Metrics */}
          <div className="grid gap-4 grid-cols-1 max-w-xs">
            <MetricCard
              title="ROI"
              value={formatMetric(performance?.roi)}
              description="Simple period growth. Profit/Loss divided by the starting portfolio value."
              trend={getTrend(performance?.roi)}
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
              description="Annualized standard deviation of returns. Measures how widely your daily returns swing up and down."
              trend={
                risk?.volatility_annualized
                  ? parseFloat(String(risk.volatility_annualized)) < 0.15
                    ? "up"
                    : parseFloat(String(risk.volatility_annualized)) > 0.25
                      ? "down"
                      : "neutral"
                  : "neutral"
              }
              isLoading={isLoading}
            />
            <MetricCard
              title="Sharpe Ratio"
              value={formatMetric(risk?.sharpe_ratio, "ratio")}
              description="Reward per unit of total risk. Compares your return to the total volatility you endured."
              trend={
                risk?.sharpe_ratio
                  ? parseFloat(String(risk.sharpe_ratio)) >= 1
                    ? "up"
                    : parseFloat(String(risk.sharpe_ratio)) < 0.5
                      ? "down"
                      : "neutral"
                  : "neutral"
              }
              isLoading={isLoading}
            />
            <MetricCard
              title="Sortino Ratio"
              value={formatMetric(risk?.sortino_ratio, "ratio")}
              description="Reward per unit of 'bad' risk. Only penalizes downside volatility (losses), ignoring upside spikes."
              trend={
                risk?.sortino_ratio
                  ? parseFloat(String(risk.sortino_ratio)) >= 2
                    ? "up"
                    : parseFloat(String(risk.sortino_ratio)) < 1
                      ? "down"
                      : "neutral"
                  : "neutral"
              }
              isLoading={isLoading}
            />
            <MetricCard
              title="Max Drawdown"
              value={formatMetric(risk?.max_drawdown)}
              description="The largest peak-to-trough decline in portfolio value."
              trend={
                risk?.max_drawdown
                  ? parseFloat(String(risk.max_drawdown)) > -0.2
                    ? "up"
                    : parseFloat(String(risk.max_drawdown)) < -0.5
                      ? "down"
                      : "neutral"
                  : "neutral"
              }
              isLoading={isLoading}
            />
          </div>

          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            <MetricCard
              title="VaR (95%)"
              value={formatMetric(risk?.var_95)}
              description="Expected worst-case loss on a typical day. Estimates the maximum loss you might expect with 95% confidence."
              trend={
                risk?.var_95
                  ? parseFloat(String(risk.var_95)) > -0.02
                    ? "up"
                    : parseFloat(String(risk.var_95)) < -0.05
                      ? "down"
                      : "neutral"
                  : "neutral"
              }
              isLoading={isLoading}
            />
            <MetricCard
              title="CVaR (95%)"
              value={formatMetric(risk?.cvar_95)}
              description="Average loss during a crash. Shows how bad the average loss is on the worst 5% of days."
              isLoading={isLoading}
            />
            <MetricCard
              title="Win Rate"
              value={formatMetric(risk?.win_rate)}
              description="Consistency of daily gains. The percentage of trading days with a positive return."
              trend={
                risk?.win_rate
                  ? parseFloat(String(risk.win_rate)) >= 0.55
                    ? "up"
                    : parseFloat(String(risk.win_rate)) < 0.45
                      ? "down"
                      : "neutral"
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
            isLoading={chartLoading || analyticsLoading}
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
            isLoading={chartLoading || analyticsLoading}
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
    </div>
  );
}
