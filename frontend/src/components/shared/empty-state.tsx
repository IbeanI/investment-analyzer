"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import {
  Briefcase,
  FileText,
  BarChart3,
  TrendingUp,
  Upload,
  Plus,
  Search,
  RefreshCw,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
  className?: string;
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center py-12 text-center",
        className
      )}
    >
      {icon && (
        <div className="rounded-full bg-muted p-4 mb-4">{icon}</div>
      )}
      <h3 className="text-lg font-semibold mb-2">{title}</h3>
      {description && (
        <p className="text-muted-foreground mb-4 max-w-sm">{description}</p>
      )}
      {action}
    </div>
  );
}

// No portfolios empty state
export function NoPortfolios() {
  return (
    <EmptyState
      icon={<Briefcase className="h-8 w-8 text-muted-foreground" />}
      title="No portfolios yet"
      description="Create your first portfolio to start tracking your investments."
      action={
        <Button asChild>
          <Link href="/portfolios/new">
            <Plus className="mr-2 h-4 w-4" />
            Create Portfolio
          </Link>
        </Button>
      }
    />
  );
}

// No transactions empty state
interface NoTransactionsProps {
  portfolioId: number;
}

export function NoTransactions({ portfolioId }: NoTransactionsProps) {
  return (
    <EmptyState
      icon={<FileText className="h-8 w-8 text-muted-foreground" />}
      title="No transactions yet"
      description="Add your first transaction or import from a CSV file to get started."
      action={
        <div className="flex gap-2">
          <Button asChild>
            <Link href={`/portfolios/${portfolioId}/transactions`}>
              <Plus className="mr-2 h-4 w-4" />
              Add Transaction
            </Link>
          </Button>
          <Button variant="outline" asChild>
            <Link href={`/portfolios/${portfolioId}/transactions?upload=true`}>
              <Upload className="mr-2 h-4 w-4" />
              Import CSV
            </Link>
          </Button>
        </div>
      }
    />
  );
}

// No holdings empty state
export function NoHoldings() {
  return (
    <EmptyState
      icon={<TrendingUp className="h-8 w-8 text-muted-foreground" />}
      title="No holdings"
      description="Your holdings will appear here once you add transactions and sync market data."
    />
  );
}

// No analytics data empty state
export function NoAnalyticsData() {
  return (
    <EmptyState
      icon={<BarChart3 className="h-8 w-8 text-muted-foreground" />}
      title="No analytics data"
      description="Analytics will be available once you have enough transaction history and market data."
    />
  );
}

// No chart data empty state
export function NoChartData({ message }: { message?: string }) {
  return (
    <div className="flex flex-col items-center justify-center h-64 text-center">
      <BarChart3 className="h-12 w-12 text-muted-foreground/50 mb-4" />
      <p className="text-muted-foreground">
        {message || "No data available for the selected period"}
      </p>
    </div>
  );
}

// No search results empty state
interface NoSearchResultsProps {
  query: string;
  onClear?: () => void;
}

export function NoSearchResults({ query, onClear }: NoSearchResultsProps) {
  return (
    <EmptyState
      icon={<Search className="h-8 w-8 text-muted-foreground" />}
      title="No results found"
      description={`No results found for "${query}". Try adjusting your search.`}
      action={
        onClear && (
          <Button variant="outline" onClick={onClear}>
            Clear search
          </Button>
        )
      }
    />
  );
}

// Sync required empty state
interface SyncRequiredProps {
  onSync?: () => void;
  isSyncing?: boolean;
}

export function SyncRequired({ onSync, isSyncing }: SyncRequiredProps) {
  return (
    <EmptyState
      icon={<RefreshCw className={cn("h-8 w-8 text-muted-foreground", isSyncing && "animate-spin")} />}
      title="Market data sync required"
      description="Sync market data to see current valuations and performance metrics."
      action={
        onSync && (
          <Button onClick={onSync} disabled={isSyncing}>
            {isSyncing ? (
              <>
                <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
                Syncing...
              </>
            ) : (
              <>
                <RefreshCw className="mr-2 h-4 w-4" />
                Sync Now
              </>
            )}
          </Button>
        )
      }
    />
  );
}

// Generic empty list
interface EmptyListProps {
  itemName: string;
  action?: ReactNode;
}

export function EmptyList({ itemName, action }: EmptyListProps) {
  return (
    <EmptyState
      title={`No ${itemName}`}
      description={`There are no ${itemName} to display.`}
      action={action}
      className="py-8"
    />
  );
}

// Coming soon placeholder
interface ComingSoonProps {
  feature: string;
}

export function ComingSoon({ feature }: ComingSoonProps) {
  return (
    <EmptyState
      icon={<BarChart3 className="h-8 w-8 text-muted-foreground" />}
      title="Coming Soon"
      description={`${feature} will be available in a future update.`}
    />
  );
}
