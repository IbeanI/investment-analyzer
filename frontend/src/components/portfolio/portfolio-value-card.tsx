"use client";

import { useEffect, useState } from "react";
import { TrendingUp, TrendingDown, Minus } from "lucide-react";
import { motion, useSpring, useTransform } from "framer-motion";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatPercentage } from "@/lib/utils";

interface PortfolioValueCardProps {
  title?: string;
  value: number | null;
  previousValue?: number | null;
  changePercent?: string | null;
  currency: string;
  isLoading?: boolean;
}

function AnimatedNumber({
  value,
  currency,
}: {
  value: number;
  currency: string;
}) {
  const spring = useSpring(0, { stiffness: 75, damping: 15 });
  const display = useTransform(spring, (current) =>
    new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(current)
  );

  useEffect(() => {
    spring.set(value);
  }, [spring, value]);

  return <motion.span>{display}</motion.span>;
}

export function PortfolioValueCard({
  title = "Portfolio Value",
  value,
  changePercent,
  currency,
  isLoading,
}: PortfolioValueCardProps) {
  const [hasAnimated, setHasAnimated] = useState(false);

  useEffect(() => {
    if (value !== null && !hasAnimated) {
      setHasAnimated(true);
    }
  }, [value, hasAnimated]);

  if (isLoading) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium text-muted-foreground">
            {title}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Skeleton className="h-10 w-40 mb-2" />
          <Skeleton className="h-5 w-20" />
        </CardContent>
      </Card>
    );
  }

  const numericChange = changePercent ? parseFloat(changePercent) : null;
  const isPositive = numericChange !== null && numericChange > 0;
  const isNegative = numericChange !== null && numericChange < 0;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="text-3xl font-bold tracking-tight">
          {value !== null ? (
            <AnimatedNumber value={value} currency={currency} />
          ) : (
            <span className="text-muted-foreground">—</span>
          )}
        </div>

        {changePercent && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className={`flex items-center gap-1 mt-1 text-sm font-medium ${
              isPositive
                ? "text-green-600 dark:text-green-500"
                : isNegative
                  ? "text-red-600 dark:text-red-500"
                  : "text-muted-foreground"
            }`}
          >
            {isPositive ? (
              <TrendingUp className="h-4 w-4" />
            ) : isNegative ? (
              <TrendingDown className="h-4 w-4" />
            ) : (
              <Minus className="h-4 w-4" />
            )}
            <span>{formatPercentage(changePercent)}</span>
            <span className="text-muted-foreground font-normal">all time</span>
          </motion.div>
        )}
      </CardContent>
    </Card>
  );
}
