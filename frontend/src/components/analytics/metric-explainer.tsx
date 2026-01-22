"use client";

import { useState } from "react";
import { ChevronDown, HelpCircle, TrendingUp, TrendingDown, Minus } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

// -----------------------------------------------------------------------------
// Metric Definitions
// -----------------------------------------------------------------------------

export interface MetricDefinition {
  name: string;
  shortDescription: string;
  longDescription: string;
  interpretation: {
    good: string;
    bad: string;
    neutral?: string;
  };
  example?: string;
  relatedMetrics?: string[];
}

export const PERFORMANCE_METRICS: Record<string, MetricDefinition> = {
  simple_return: {
    name: "Simple Return",
    shortDescription: "Total percentage gain or loss",
    longDescription:
      "Simple return measures the total percentage change in your portfolio value from the start to the end of the period. It's the most straightforward way to see how much you've gained or lost.",
    interpretation: {
      good: "A positive return means your investments have grown in value.",
      bad: "A negative return means your investments have lost value.",
      neutral: "A zero return means your portfolio value is unchanged.",
    },
    example:
      "If you invested $10,000 and it's now worth $11,500, your simple return is +15%.",
  },
  twr: {
    name: "Time-Weighted Return (TWR)",
    shortDescription: "Performance excluding deposit/withdrawal timing",
    longDescription:
      "TWR measures how well your investments performed, independent of when you added or withdrew money. It's useful for comparing your investment decisions against benchmarks or other investors.",
    interpretation: {
      good: "A higher TWR means your investment choices performed well.",
      bad: "A lower TWR suggests your investment picks underperformed.",
    },
    example:
      "TWR ignores the fact that you added $5,000 right before a market drop. It shows the pure investment performance.",
    relatedMetrics: ["simple_return", "xirr"],
  },
  xirr: {
    name: "XIRR (Extended IRR)",
    shortDescription: "Your actual annualized return",
    longDescription:
      "XIRR calculates your true annualized return, accounting for the timing and size of all your deposits and withdrawals. It's the most accurate measure of your personal investment success.",
    interpretation: {
      good: "An XIRR higher than inflation (typically 2-3%) means you're growing wealth in real terms.",
      bad: "A negative XIRR means you're losing money on your investments.",
    },
    example:
      "If your XIRR is 8%, investing $100 at the start of each year would result in the same outcome as getting 8% annually.",
  },
  cagr: {
    name: "CAGR",
    shortDescription: "Compound Annual Growth Rate",
    longDescription:
      "CAGR shows the steady annual growth rate that would give you the same final result. It smooths out volatility to show consistent year-over-year growth.",
    interpretation: {
      good: "A CAGR of 7-10% is historically excellent for long-term stock investing.",
      bad: "A CAGR below inflation means your purchasing power is decreasing.",
    },
    example:
      "If $10,000 grew to $19,000 over 5 years, the CAGR is about 13.7% per year.",
  },
};

export const RISK_METRICS: Record<string, MetricDefinition> = {
  volatility: {
    name: "Volatility",
    shortDescription: "How much your portfolio swings up and down",
    longDescription:
      "Volatility measures the standard deviation of your returns, annualized. Higher volatility means bigger swings in value—both up and down. It's a key measure of investment risk.",
    interpretation: {
      good: "Lower volatility (under 15%) means smoother returns with fewer surprises.",
      bad: "High volatility (over 25%) means large swings that can be stressful.",
      neutral: "Moderate volatility (15-20%) is typical for a diversified stock portfolio.",
    },
    example:
      "A portfolio with 20% volatility might swing between +40% and -40% in extreme years.",
  },
  sharpe_ratio: {
    name: "Sharpe Ratio",
    shortDescription: "Return per unit of risk taken",
    longDescription:
      "The Sharpe ratio divides your excess return (above risk-free rate) by your volatility. It tells you if you're being adequately compensated for the risks you're taking.",
    interpretation: {
      good: "Above 1.0 is good; above 2.0 is excellent.",
      bad: "Below 0.5 suggests you could get similar returns with less risk.",
      neutral: "Between 0.5 and 1.0 is acceptable for most portfolios.",
    },
    example:
      "A Sharpe of 1.5 means you're earning 1.5% extra return for every 1% of volatility.",
    relatedMetrics: ["volatility", "sortino_ratio"],
  },
  sortino_ratio: {
    name: "Sortino Ratio",
    shortDescription: "Return per unit of downside risk",
    longDescription:
      "Like Sharpe, but only considers downside volatility (losses). This is often more relevant since investors care more about losses than gains.",
    interpretation: {
      good: "Above 2.0 is very good—high returns with limited downside.",
      bad: "Below 1.0 suggests excessive downside risk.",
    },
    example:
      "A high Sortino but low Sharpe means you have upside volatility (good!) but limited downside.",
    relatedMetrics: ["sharpe_ratio", "max_drawdown"],
  },
  max_drawdown: {
    name: "Maximum Drawdown",
    shortDescription: "Worst peak-to-trough decline",
    longDescription:
      "Max drawdown shows the largest percentage drop from a peak to a trough. It answers: \"What's the worst loss I would have experienced if I bought at the top?\"",
    interpretation: {
      good: "Under 20% means relatively controlled losses.",
      bad: "Over 50% means you would have lost more than half your money at the worst point.",
    },
    example:
      "A max drawdown of -30% means at the worst point, your $100,000 would have dropped to $70,000.",
  },
  var_95: {
    name: "Value at Risk (VaR 95%)",
    shortDescription: "Worst expected daily loss, 95% confident",
    longDescription:
      "VaR estimates the maximum loss you might experience on a typical bad day. At 95% confidence, losses should exceed this only about 1 day in 20.",
    interpretation: {
      good: "A VaR under 2% means limited daily downside risk.",
      bad: "A VaR over 5% means significant daily swings are possible.",
    },
    example:
      "A VaR of -3% on a $100,000 portfolio means you could lose $3,000 in a single bad day (but worse days can still happen).",
    relatedMetrics: ["cvar_95"],
  },
  cvar_95: {
    name: "Conditional VaR (CVaR 95%)",
    shortDescription: "Average loss on worst days",
    longDescription:
      "CVaR (also called Expected Shortfall) tells you the average loss when VaR is exceeded. It captures tail risk—what happens in worst-case scenarios.",
    interpretation: {
      good: "CVaR close to VaR means limited tail risk.",
      bad: "CVaR much worse than VaR means rare but severe losses are possible.",
    },
    example:
      "If VaR is -3% but CVaR is -6%, the worst 5% of days average a 6% loss.",
    relatedMetrics: ["var_95"],
  },
  win_rate: {
    name: "Win Rate",
    shortDescription: "Percentage of profitable days",
    longDescription:
      "Win rate shows how often your portfolio goes up vs. down. While seemingly simple, combined with average win/loss size, it reveals your portfolio's character.",
    interpretation: {
      good: "Above 55% is excellent—you're positive more often than not.",
      bad: "Below 45% means frequent losses (though you can still profit if wins are bigger).",
      neutral: "Around 50% is typical for most portfolios.",
    },
    example:
      "A 52% win rate over 250 trading days means about 130 up days vs. 120 down days.",
  },
};

export const BENCHMARK_METRICS: Record<string, MetricDefinition> = {
  alpha: {
    name: "Alpha",
    shortDescription: "Excess return vs. benchmark",
    longDescription:
      "Alpha measures how much better (or worse) your portfolio performed compared to what would be expected given your market exposure (beta). Positive alpha means you're adding value.",
    interpretation: {
      good: "Positive alpha means you're beating the market on a risk-adjusted basis.",
      bad: "Negative alpha means you'd have been better off with an index fund.",
    },
    example:
      "An alpha of +2% means you outperformed the benchmark by 2% annually after adjusting for risk.",
    relatedMetrics: ["beta"],
  },
  beta: {
    name: "Beta",
    shortDescription: "Sensitivity to market movements",
    longDescription:
      "Beta measures how much your portfolio moves relative to the market. A beta of 1 means you move with the market; higher means more volatile, lower means more stable.",
    interpretation: {
      good: "Beta near 1 means market-like behavior (good for tracking).",
      bad: "Very high beta (>1.5) means amplified risk in downturns.",
      neutral: "Beta below 1 is more defensive but may lag in bull markets.",
    },
    example:
      "A beta of 1.2 means if the market drops 10%, your portfolio might drop 12%.",
    relatedMetrics: ["alpha", "correlation"],
  },
  correlation: {
    name: "Correlation",
    shortDescription: "How closely you track the benchmark",
    longDescription:
      "Correlation measures how much your portfolio moves in the same direction as the benchmark. High correlation means similar patterns; low correlation provides diversification benefits.",
    interpretation: {
      good: "Low correlation (under 0.5) provides diversification.",
      bad: "Very low correlation might mean you're not exposed to market growth.",
      neutral: "Correlation of 0.7-0.9 is typical for diversified portfolios.",
    },
    example:
      "A correlation of 0.85 means 85% of your portfolio's movement can be explained by the benchmark.",
    relatedMetrics: ["beta", "r_squared"],
  },
  tracking_error: {
    name: "Tracking Error",
    shortDescription: "Deviation from benchmark returns",
    longDescription:
      "Tracking error measures how much your returns differ from the benchmark over time. Lower tracking error means closer index-like performance.",
    interpretation: {
      good: "Low tracking error (under 5%) if you want benchmark-like returns.",
      bad: "High tracking error is bad if you intended to track an index.",
      neutral: "Active managers typically have 5-10% tracking error.",
    },
    example:
      "A tracking error of 8% means your returns might be 8% above or below the benchmark in any given period.",
  },
};

// -----------------------------------------------------------------------------
// Component
// -----------------------------------------------------------------------------

interface MetricExplainerProps {
  category: "performance" | "risk" | "benchmark";
  className?: string;
}

export function MetricExplainer({ category, className }: MetricExplainerProps) {
  const [isOpen, setIsOpen] = useState(false);

  const metrics =
    category === "performance"
      ? PERFORMANCE_METRICS
      : category === "risk"
        ? RISK_METRICS
        : BENCHMARK_METRICS;

  const categoryTitle =
    category === "performance"
      ? "Performance Metrics"
      : category === "risk"
        ? "Risk Metrics"
        : "Benchmark Metrics";

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen} className={className}>
      <CollapsibleTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="flex items-center gap-2 text-muted-foreground hover:text-foreground"
        >
          <HelpCircle className="h-4 w-4" />
          <span>What do these metrics mean?</span>
          <ChevronDown
            className={cn(
              "h-4 w-4 transition-transform",
              isOpen && "rotate-180"
            )}
          />
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent className="mt-4">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">{categoryTitle} Explained</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {Object.entries(metrics).map(([key, metric]) => (
              <MetricExplanationItem key={key} metric={metric} />
            ))}
          </CardContent>
        </Card>
      </CollapsibleContent>
    </Collapsible>
  );
}

interface MetricExplanationItemProps {
  metric: MetricDefinition;
}

function MetricExplanationItem({ metric }: MetricExplanationItemProps) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="border-b pb-3 last:border-0 last:pb-0">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full text-left flex items-start justify-between gap-2"
      >
        <div>
          <h4 className="font-medium text-sm">{metric.name}</h4>
          <p className="text-sm text-muted-foreground">
            {metric.shortDescription}
          </p>
        </div>
        <ChevronDown
          className={cn(
            "h-4 w-4 mt-1 shrink-0 text-muted-foreground transition-transform",
            expanded && "rotate-180"
          )}
        />
      </button>

      {expanded && (
        <div className="mt-3 space-y-3 text-sm">
          <p className="text-muted-foreground">{metric.longDescription}</p>

          <div className="space-y-1.5">
            <div className="flex items-start gap-2">
              <TrendingUp className="h-4 w-4 text-green-600 shrink-0 mt-0.5" />
              <p className="text-green-600 dark:text-green-500">
                {metric.interpretation.good}
              </p>
            </div>
            <div className="flex items-start gap-2">
              <TrendingDown className="h-4 w-4 text-red-600 shrink-0 mt-0.5" />
              <p className="text-red-600 dark:text-red-500">
                {metric.interpretation.bad}
              </p>
            </div>
            {metric.interpretation.neutral && (
              <div className="flex items-start gap-2">
                <Minus className="h-4 w-4 text-muted-foreground shrink-0 mt-0.5" />
                <p className="text-muted-foreground">
                  {metric.interpretation.neutral}
                </p>
              </div>
            )}
          </div>

          {metric.example && (
            <div className="bg-muted/50 rounded-md p-2">
              <p className="text-xs text-muted-foreground">
                <strong>Example:</strong> {metric.example}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// -----------------------------------------------------------------------------
// Individual Metric Card with Explanation
// -----------------------------------------------------------------------------

interface MetricCardWithExplanationProps {
  title: string;
  value: string | null;
  metricKey: string;
  category: "performance" | "risk" | "benchmark";
  trend?: "up" | "down" | "neutral";
  isLoading?: boolean;
}

export function MetricCardWithExplanation({
  title,
  value,
  metricKey,
  category,
  trend,
  isLoading,
}: MetricCardWithExplanationProps) {
  const [showExplanation, setShowExplanation] = useState(false);

  const metrics =
    category === "performance"
      ? PERFORMANCE_METRICS
      : category === "risk"
        ? RISK_METRICS
        : BENCHMARK_METRICS;

  const metric = metrics[metricKey];

  if (isLoading) {
    return (
      <Card>
        <CardContent className="pt-4">
          <div className="h-4 w-20 bg-muted animate-pulse rounded mb-2" />
          <div className="h-8 w-24 bg-muted animate-pulse rounded" />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="relative">
      <CardContent className="pt-4">
        <div className="flex items-center justify-between mb-1">
          <span className="text-sm text-muted-foreground">{title}</span>
          {metric && (
            <button
              onClick={() => setShowExplanation(!showExplanation)}
              className="text-muted-foreground hover:text-foreground"
            >
              <HelpCircle className="h-4 w-4" />
            </button>
          )}
        </div>
        <div
          className={cn(
            "text-2xl font-bold",
            trend === "up" && "text-green-600 dark:text-green-500",
            trend === "down" && "text-red-600 dark:text-red-500"
          )}
        >
          {value ?? "—"}
        </div>

        {showExplanation && metric && (
          <div className="mt-3 pt-3 border-t text-sm space-y-2">
            <p className="text-muted-foreground">{metric.longDescription}</p>
            <div className="flex items-start gap-2">
              <TrendingUp className="h-3 w-3 text-green-600 shrink-0 mt-1" />
              <p className="text-xs text-green-600 dark:text-green-500">
                {metric.interpretation.good}
              </p>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
