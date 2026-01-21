"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getPortfolios,
  getPortfolio,
  createPortfolio,
  updatePortfolio,
  deletePortfolio,
  getPortfolioValuation,
  getPortfolioHistory,
  getPortfolioAnalytics,
  triggerSync,
  getSyncStatus,
} from "@/lib/api/portfolios";
import type {
  PortfolioCreate,
  PortfolioUpdate,
} from "@/types/api";
import { toast } from "sonner";

// -----------------------------------------------------------------------------
// Query Keys
// -----------------------------------------------------------------------------

export const portfolioKeys = {
  all: ["portfolios"] as const,
  lists: () => [...portfolioKeys.all, "list"] as const,
  list: (filters: string) => [...portfolioKeys.lists(), { filters }] as const,
  details: () => [...portfolioKeys.all, "detail"] as const,
  detail: (id: number) => [...portfolioKeys.details(), id] as const,
  valuation: (id: number) => [...portfolioKeys.detail(id), "valuation"] as const,
  history: (id: number, from: string, to: string, interval: string) =>
    [...portfolioKeys.detail(id), "history", from, to, interval] as const,
  analytics: (id: number, from: string, to: string) =>
    [...portfolioKeys.detail(id), "analytics", from, to] as const,
  syncStatus: (id: number) => [...portfolioKeys.detail(id), "sync-status"] as const,
};

// -----------------------------------------------------------------------------
// Queries
// -----------------------------------------------------------------------------

/**
 * Hook to fetch all portfolios
 */
export function usePortfolios() {
  return useQuery({
    queryKey: portfolioKeys.lists(),
    queryFn: () => getPortfolios(),
  });
}

/**
 * Hook to fetch a single portfolio
 */
export function usePortfolio(id: number) {
  return useQuery({
    queryKey: portfolioKeys.detail(id),
    queryFn: () => getPortfolio(id),
    enabled: !!id,
  });
}

/**
 * Hook to fetch portfolio valuation
 */
export function usePortfolioValuation(id: number, date?: string) {
  return useQuery({
    queryKey: portfolioKeys.valuation(id),
    queryFn: () => getPortfolioValuation(id, date),
    enabled: !!id,
  });
}

/**
 * Hook to fetch portfolio history
 */
export function usePortfolioHistory(
  id: number,
  fromDate: string,
  toDate: string,
  interval: "daily" | "weekly" | "monthly" = "daily"
) {
  return useQuery({
    queryKey: portfolioKeys.history(id, fromDate, toDate, interval),
    queryFn: () => getPortfolioHistory(id, fromDate, toDate, interval),
    enabled: !!id && !!fromDate && !!toDate,
  });
}

/**
 * Hook to fetch portfolio analytics
 */
export function usePortfolioAnalytics(
  id: number,
  fromDate: string,
  toDate: string,
  benchmarkSymbol?: string,
  riskFreeRate?: string
) {
  return useQuery({
    queryKey: portfolioKeys.analytics(id, fromDate, toDate),
    queryFn: () =>
      getPortfolioAnalytics(id, fromDate, toDate, benchmarkSymbol, riskFreeRate),
    enabled: !!id && !!fromDate && !!toDate,
  });
}

/**
 * Hook to fetch sync status
 */
export function useSyncStatus(id: number) {
  return useQuery({
    queryKey: portfolioKeys.syncStatus(id),
    queryFn: () => getSyncStatus(id),
    enabled: !!id,
    refetchInterval: (query) => {
      // Poll every 2 seconds if sync is in progress
      const status = query.state.data?.status;
      return status === "IN_PROGRESS" || status === "PENDING" ? 2000 : false;
    },
  });
}

// -----------------------------------------------------------------------------
// Mutations
// -----------------------------------------------------------------------------

/**
 * Hook to create a portfolio
 */
export function useCreatePortfolio() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: PortfolioCreate) => createPortfolio(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: portfolioKeys.lists() });
      toast.success("Portfolio created successfully");
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to create portfolio");
    },
  });
}

/**
 * Hook to update a portfolio
 */
export function useUpdatePortfolio() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: PortfolioUpdate }) =>
      updatePortfolio(id, data),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: portfolioKeys.detail(id) });
      queryClient.invalidateQueries({ queryKey: portfolioKeys.lists() });
      toast.success("Portfolio updated successfully");
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to update portfolio");
    },
  });
}

/**
 * Hook to delete a portfolio
 */
export function useDeletePortfolio() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: number) => deletePortfolio(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: portfolioKeys.lists() });
      toast.success("Portfolio deleted successfully");
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to delete portfolio");
    },
  });
}

/**
 * Hook to trigger market data sync
 */
export function useTriggerSync() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: number) => triggerSync(id),
    onSuccess: (_, id) => {
      queryClient.invalidateQueries({ queryKey: portfolioKeys.syncStatus(id) });
      toast.success("Market data sync started");
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to start sync");
    },
  });
}
