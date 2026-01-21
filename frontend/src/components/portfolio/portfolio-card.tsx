"use client";

import Link from "next/link";
import { TrendingUp, TrendingDown, MoreHorizontal, Trash2, Settings, BarChart3 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCurrency, formatPercentage } from "@/lib/utils";
import type { Portfolio } from "@/types/api";

interface PortfolioCardProps {
  portfolio: Portfolio;
  totalValue?: string | null;
  changePercent?: string | null;
  onDelete?: (id: number) => void;
}

export function PortfolioCard({
  portfolio,
  totalValue,
  changePercent,
  onDelete,
}: PortfolioCardProps) {
  const isPositive = changePercent && parseFloat(changePercent) > 0;
  const isNegative = changePercent && parseFloat(changePercent) < 0;

  return (
    <Card className="group relative hover:bg-accent/50 transition-colors">
      <Link href={`/portfolios/${portfolio.id}`} className="absolute inset-0 z-0" />

      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg truncate pr-2">{portfolio.name}</CardTitle>
          <div className="flex items-center gap-2">
            <Badge variant="secondary">{portfolio.currency}</Badge>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 relative z-10 opacity-0 group-hover:opacity-100 transition-opacity"
                  onClick={(e) => e.stopPropagation()}
                >
                  <MoreHorizontal className="h-4 w-4" />
                  <span className="sr-only">Actions</span>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem asChild>
                  <Link href={`/portfolios/${portfolio.id}/analytics`}>
                    <BarChart3 className="mr-2 h-4 w-4" />
                    Analytics
                  </Link>
                </DropdownMenuItem>
                <DropdownMenuItem asChild>
                  <Link href={`/portfolios/${portfolio.id}/settings`}>
                    <Settings className="mr-2 h-4 w-4" />
                    Settings
                  </Link>
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  className="text-destructive focus:text-destructive"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDelete?.(portfolio.id);
                  }}
                >
                  <Trash2 className="mr-2 h-4 w-4" />
                  Delete
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </CardHeader>

      <CardContent>
        <div className="space-y-1">
          {totalValue ? (
            <>
              <div className="text-2xl font-bold">
                {formatCurrency(totalValue, portfolio.currency)}
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
              Sync to see valuation
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

export function PortfolioCardSkeleton() {
  return (
    <Card>
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
  );
}
