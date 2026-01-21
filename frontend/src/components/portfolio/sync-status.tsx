"use client";

import { RefreshCw, CheckCircle2, XCircle, Clock, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useSyncStatus, useTriggerSync } from "@/hooks/use-portfolios";
import { formatDate } from "@/lib/utils";
import type { SyncStatus as SyncStatusType } from "@/types/api";

interface SyncStatusProps {
  portfolioId: number;
  compact?: boolean;
}

function getStatusIcon(status: SyncStatusType | undefined) {
  switch (status) {
    case "COMPLETED":
      return <CheckCircle2 className="h-4 w-4 text-green-500" />;
    case "FAILED":
      return <XCircle className="h-4 w-4 text-red-500" />;
    case "IN_PROGRESS":
    case "PENDING":
      return <Loader2 className="h-4 w-4 animate-spin text-blue-500" />;
    case "PARTIAL":
      return <Clock className="h-4 w-4 text-yellow-500" />;
    default:
      return <Clock className="h-4 w-4 text-muted-foreground" />;
  }
}

function getStatusVariant(
  status: SyncStatusType | undefined
): "default" | "secondary" | "destructive" | "outline" {
  switch (status) {
    case "COMPLETED":
      return "default";
    case "FAILED":
      return "destructive";
    case "IN_PROGRESS":
    case "PENDING":
      return "secondary";
    default:
      return "outline";
  }
}

export function SyncStatus({ portfolioId, compact = false }: SyncStatusProps) {
  const { data: syncStatus, isLoading } = useSyncStatus(portfolioId);
  const triggerSync = useTriggerSync();

  const isSyncing =
    syncStatus?.status === "IN_PROGRESS" || syncStatus?.status === "PENDING";

  if (compact) {
    return (
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="outline"
              size="icon"
              onClick={() => triggerSync.mutate(portfolioId)}
              disabled={isSyncing || triggerSync.isPending}
            >
              {isSyncing || triggerSync.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="h-4 w-4" />
              )}
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            <p>
              {isSyncing
                ? "Syncing market data..."
                : syncStatus?.completed_at
                  ? `Last synced: ${formatDate(syncStatus.completed_at)}`
                  : "Sync market data"}
            </p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }

  return (
    <div className="flex items-center gap-3">
      {/* Status badge */}
      {isLoading ? (
        <Badge variant="outline">Loading...</Badge>
      ) : (
        <Badge variant={getStatusVariant(syncStatus?.status)}>
          <span className="flex items-center gap-1.5">
            {getStatusIcon(syncStatus?.status)}
            {syncStatus?.status || "NEVER"}
          </span>
        </Badge>
      )}

      {/* Last sync info */}
      {syncStatus?.completed_at && !isSyncing && (
        <span className="text-sm text-muted-foreground hidden sm:inline">
          Last sync: {formatDate(syncStatus.completed_at)}
        </span>
      )}

      {/* Sync stats */}
      {syncStatus?.assets_synced !== undefined && syncStatus.assets_synced > 0 && (
        <span className="text-sm text-muted-foreground hidden sm:inline">
          ({syncStatus.assets_synced} assets
          {syncStatus.assets_failed > 0 && `, ${syncStatus.assets_failed} failed`})
        </span>
      )}

      {/* Sync button */}
      <Button
        variant="outline"
        size="sm"
        onClick={() => triggerSync.mutate(portfolioId)}
        disabled={isSyncing || triggerSync.isPending}
      >
        {isSyncing || triggerSync.isPending ? (
          <>
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            Syncing...
          </>
        ) : (
          <>
            <RefreshCw className="mr-2 h-4 w-4" />
            Sync
          </>
        )}
      </Button>
    </div>
  );
}
