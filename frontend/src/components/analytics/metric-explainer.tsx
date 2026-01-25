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
  totalValue: {
    name: "Total Value",
    shortDescription: "Liquidation value of your portfolio",
    longDescription:
      "The estimated amount you would receive if you sold all your holdings today at current market prices. This is the sum of your Net Invested capital plus your accumulated Total P/L.",
    interpretation: {
      good: "A higher value indicates portfolio growth from your investments.",
      bad: "A lower value than your Net Invested means you have unrealized losses.",
      neutral: "Equal to Net Invested means you're at break-even.",
    },
    example:
      "You invested €45,000 and made €17,000 profit. Your Total Value is €62,000.",
  },
  netInvested: {
    name: "Net Invested",
    shortDescription: "Your total principal capital",
    longDescription:
      "The total amount of cash you have personally contributed from your bank account (Total Deposits/Buys minus Total Withdrawals/Sales).",
    interpretation: {
      good: "Positive means you have added more money than you have withdrawn.",
      bad: "Negative means you have withdrawn more than you deposited (taking profits out).",
      neutral: "Zero means you have withdrawn exactly as much as you deposited.",
    },
    example:
      "You deposited €50,000 and later withdrew €5,000. Your Net Invested is €45,000.",
  },
  totalPnl: {
    name: "Total P/L",
    shortDescription: "Total profit/loss since inception",
    longDescription:
      "The absolute financial growth of your portfolio relative to your total Net Invested capital since day one.",
    interpretation: {
      good: "Positive means you have made money on your invested capital.",
      bad: "Negative means you have lost part of your invested capital.",
      neutral: "Zero means you have exactly the same amount you invested (break-even).",
    },
    example:
      "You put in €10,000 total. Your portfolio is now worth €13,000. Your Total P/L is +€3,000 (+30%).",
  },
  twr: {
    name: "TWR (Time-Weighted Return)",
    shortDescription: "Strategy performance (Skill)",
    longDescription:
      "Measures how well your investments performed, ignoring the timing of your deposits and withdrawals. This is the best metric to compare yourself against a benchmark (like the S&P 500).",
    interpretation: {
      good: "Positive means your investment selections increased in value.",
      bad: "Negative means your investment selections decreased in value.",
      neutral: "Zero means your investment selections neither gained nor lost value.",
    },
    example:
      "You deposit €1M just before a market drop. You lose money personally, but TWR ignores the bad timing and only measures how the assets performed.",
  },
  xirr: {
    name: "XIRR (Extended IRR)",
    shortDescription: "Personal effective return (Wallet)",
    longDescription:
      "Your actual annualized return, accounting for the timing of every single deposit and withdrawal. It reflects your personal experience as an investor.",
    interpretation: {
      good: "Higher than inflation (typically >3%) means you are growing real wealth.",
      bad: "Negative means you are losing money on a personal basis.",
      neutral: "Zero means your return is equivalent to keeping cash under a mattress.",
    },
    example:
      "An XIRR of 8% means your portfolio generated the same result as a savings account paying 8% interest per year.",
  },
  roi: {
    name: "ROI (Return on Investment)",
    shortDescription: "Simple period growth",
    longDescription:
      "The percentage growth of your balance during a specific timeframe. Calculated as the Profit/Loss divided by the Starting Value of that period.",
    interpretation: {
      good: "Positive means your balance grew during this period.",
      bad: "Negative means your balance shrank during this period.",
      neutral: "Zero means your portfolio value is unchanged.",
    },
    example:
      "You started the month with €1,000 and made €50 profit. Your ROI is +5%.",
  },
};

export const RISK_METRICS: Record<string, MetricDefinition> = {
  volatility: {
    name: "Volatility",
    shortDescription: "Annualized standard deviation of returns.",
    longDescription:
      "Measures how widely your daily returns swing up and down.",
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
    shortDescription: "Reward per unit of total risk.",
    longDescription:
      "Compares your return to the total volatility you endured. It helps answer: \"Was the return worth the stress?\"",
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
    shortDescription: "Reward per unit of \"bad\" risk.",
    longDescription:
      "Similar to the Sharpe Ratio, but only penalizes you for downside volatility (losses). It ignores upside volatility (sudden spikes in profit).",
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
    name: "VaR (Value at Risk 95%)",
    shortDescription: "Expected worst-case loss on a typical day.",
    longDescription:
      "Estimates the maximum loss you might expect on a \"bad day\" with 95% confidence.",
    interpretation: {
      good: "A VaR under 2% means limited daily downside risk.",
      bad: "A VaR over 5% means significant daily swings are possible.",
    },
    example:
      "A VaR of -3% on a $100,000 portfolio means you could lose $3,000 in a single bad day (but worse days can still happen).",
    relatedMetrics: ["cvar_95"],
  },
  cvar_95: {
    name: "CVaR (Conditional VaR 95%)",
    shortDescription: "Average loss during a crash.",
    longDescription:
      "If the market does break the VaR limit (the worst 5% of days), this metric tells you how bad the average loss is. It is the \"average of the disasters.\"",
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
    shortDescription: "Consistency of daily gains.",
    longDescription:
      "The percentage of trading days where your portfolio ended with a positive return.",
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
