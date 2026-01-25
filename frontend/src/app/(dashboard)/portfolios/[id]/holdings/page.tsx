"use client";

import { use } from "react";
import Link from "next/link";
import { ArrowLeft, AlertCircle, Plus } from "lucide-react";
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
import { HoldingsTable, PortfolioNav, SyncStatus } from "@/components/portfolio";
import {
  usePortfolio,
  usePortfolioValuation,
  useSyncStatus,
} from "@/hooks/use-portfolios";
import { formatDate } from "@/lib/utils";
import { SyncRequired } from "@/components/shared/empty-state";
import { useTriggerSync } from "@/hooks/use-portfolios";

// -----------------------------------------------------------------------------
// Holdings Page
// -----------------------------------------------------------------------------

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function HoldingsPage({ params }: PageProps) {
  const { id } = use(params);
  const portfolioId = parseInt(id, 10);

  const {
    data: portfolio,
    isLoading: portfolioLoading,
    error: portfolioError,
  } = usePortfolio(portfolioId);
  const {
    data: valuation,
    isLoading: valuationLoading,
  } = usePortfolioValuation(portfolioId);
  const { data: syncStatus } = useSyncStatus(portfolioId);
  const triggerSync = useTriggerSync();

  if (portfolioLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-10 w-96" />
        <Card>
          <CardHeader>
            <Skeleton className="h-6 w-32" />
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {[1, 2, 3, 4, 5].map((i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          </CardContent>
        </Card>
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

  const holdings = valuation?.holdings || [];
  const currency = portfolio.currency;
  const needsSync = syncStatus?.status === "NEVER" || !syncStatus?.status;
  const isSyncing = syncStatus?.status === "IN_PROGRESS" || syncStatus?.status === "PENDING";

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
            <h1 className="text-2xl font-bold tracking-tight">{portfolio.name}</h1>
            <p className="text-sm text-muted-foreground">
              {holdings.length} holding{holdings.length !== 1 ? "s" : ""}
            </p>
          </div>
        </div>
        <SyncStatus portfolioId={portfolioId} />
      </div>

      {/* Navigation */}
      <PortfolioNav portfolioId={portfolioId} />

      {/* Content */}
      {needsSync ? (
        <SyncRequired
          onSync={() => triggerSync.mutate(portfolioId)}
          isSyncing={isSyncing || triggerSync.isPending}
        />
      ) : valuationLoading ? (
        <Card>
          <CardHeader>
            <Skeleton className="h-6 w-32" />
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {[1, 2, 3, 4, 5].map((i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          </CardContent>
        </Card>
      ) : holdings.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12">
            <p className="text-muted-foreground mb-4">No holdings yet</p>
            <Button asChild>
              <Link href={`/portfolios/${portfolioId}/transactions`}>
                <Plus className="mr-2 h-4 w-4" />
                Add Transaction
              </Link>
            </Button>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <div>
              <CardTitle>Holdings</CardTitle>
              <CardDescription>
                {valuation?.valuation_date
                  ? `As of ${formatDate(valuation.valuation_date)}`
                  : "Current positions"}
              </CardDescription>
            </div>
            <Button asChild size="sm">
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
      )}
    </div>
  );
}
