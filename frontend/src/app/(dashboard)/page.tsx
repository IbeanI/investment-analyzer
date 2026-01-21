"use client";

import Link from "next/link";
import { Plus, TrendingUp, TrendingDown, Briefcase } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { usePortfolios } from "@/hooks/use-portfolios";
import { useAuth } from "@/providers";
import { formatCurrency, formatPercentage } from "@/lib/utils";

// -----------------------------------------------------------------------------
// Portfolio Card Component
// -----------------------------------------------------------------------------

interface PortfolioCardProps {
  id: number;
  name: string;
  currency: string;
  // These would come from valuation data in a real implementation
  totalValue?: string | null;
  changePercent?: string | null;
}

function PortfolioCard({
  id,
  name,
  currency,
  totalValue,
  changePercent,
}: PortfolioCardProps) {
  const isPositive =
    changePercent && parseFloat(changePercent) > 0;
  const isNegative =
    changePercent && parseFloat(changePercent) < 0;

  return (
    <Link href={`/portfolios/${id}`}>
      <Card className="h-full hover:bg-accent/50 transition-colors cursor-pointer">
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-lg">{name}</CardTitle>
            <Badge variant="secondary">{currency}</Badge>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-1">
            {totalValue ? (
              <>
                <div className="text-2xl font-bold">
                  {formatCurrency(totalValue, currency)}
                </div>
                {changePercent && (
                  <div
                    className={`flex items-center gap-1 text-sm ${
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
                    ) : null}
                    <span>{formatPercentage(changePercent)}</span>
                  </div>
                )}
              </>
            ) : (
              <p className="text-sm text-muted-foreground">
                Sync market data to see valuation
              </p>
            )}
          </div>
        </CardContent>
      </Card>
    </Link>
  );
}

// -----------------------------------------------------------------------------
// Empty State Component
// -----------------------------------------------------------------------------

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-center">
      <div className="rounded-full bg-muted p-4 mb-4">
        <Briefcase className="h-8 w-8 text-muted-foreground" />
      </div>
      <h3 className="text-lg font-semibold mb-2">No portfolios yet</h3>
      <p className="text-muted-foreground mb-4 max-w-sm">
        Create your first portfolio to start tracking your investments and
        analyzing performance.
      </p>
      <Button asChild>
        <Link href="/portfolios/new">
          <Plus className="mr-2 h-4 w-4" />
          Create Portfolio
        </Link>
      </Button>
    </div>
  );
}

// -----------------------------------------------------------------------------
// Loading State Component
// -----------------------------------------------------------------------------

function LoadingState() {
  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      {[1, 2, 3].map((i) => (
        <Card key={i}>
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <Skeleton className="h-5 w-32" />
              <Skeleton className="h-5 w-12" />
            </div>
          </CardHeader>
          <CardContent className="space-y-2">
            <Skeleton className="h-8 w-24" />
            <Skeleton className="h-4 w-16" />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

// -----------------------------------------------------------------------------
// Home Page
// -----------------------------------------------------------------------------

export default function HomePage() {
  const { user } = useAuth();
  const { data, isLoading, error } = usePortfolios();

  const portfolios = data?.items || [];

  // Get greeting based on time of day
  const getGreeting = () => {
    const hour = new Date().getHours();
    if (hour < 12) return "Good morning";
    if (hour < 18) return "Good afternoon";
    return "Good evening";
  };

  return (
    <div className="space-y-6">
      {/* Welcome header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            {getGreeting()}
            {user?.full_name ? `, ${user.full_name.split(" ")[0]}` : ""}
          </h1>
          <p className="text-muted-foreground">
            {portfolios.length > 0
              ? "Here's an overview of your portfolios"
              : "Get started by creating your first portfolio"}
          </p>
        </div>
        {portfolios.length > 0 && (
          <Button asChild>
            <Link href="/portfolios/new">
              <Plus className="mr-2 h-4 w-4" />
              New Portfolio
            </Link>
          </Button>
        )}
      </div>

      {/* Content */}
      {isLoading ? (
        <LoadingState />
      ) : error ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-destructive">Error</CardTitle>
            <CardDescription>Failed to load portfolios</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              {error instanceof Error ? error.message : "An error occurred"}
            </p>
          </CardContent>
        </Card>
      ) : portfolios.length === 0 ? (
        <EmptyState />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {portfolios.map((portfolio) => (
            <PortfolioCard
              key={portfolio.id}
              id={portfolio.id}
              name={portfolio.name}
              currency={portfolio.currency}
              // In a real implementation, you'd fetch valuation data
              // and pass totalValue and changePercent here
            />
          ))}
        </div>
      )}
    </div>
  );
}
