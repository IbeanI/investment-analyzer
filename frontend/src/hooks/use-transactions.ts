"use client";

import { useQuery, useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getTransactions,
  createTransaction,
  updateTransaction,
  deleteTransaction,
  uploadTransactions,
  AmbiguousDateFormatException,
} from "@/lib/api/transactions";
import type { TransactionCreate, TransactionUpdate, UploadDateFormat } from "@/types/api";
import { toast } from "@/lib/toast";
import { portfolioKeys } from "./use-portfolios";

// -----------------------------------------------------------------------------
// Query Keys
// -----------------------------------------------------------------------------

export const transactionKeys = {
  all: ["transactions"] as const,
  lists: () => [...transactionKeys.all, "list"] as const,
  list: (portfolioId: number) =>
    [...transactionKeys.lists(), portfolioId] as const,
  details: () => [...transactionKeys.all, "detail"] as const,
  detail: (portfolioId: number, transactionId: number) =>
    [...transactionKeys.details(), portfolioId, transactionId] as const,
};

// -----------------------------------------------------------------------------
// Queries
// -----------------------------------------------------------------------------

/**
 * Hook to fetch transactions for a portfolio
 */
export function useTransactions(portfolioId: number, skip = 0, limit = 100) {
  return useQuery({
    queryKey: [...transactionKeys.list(portfolioId), skip, limit],
    queryFn: () => getTransactions(portfolioId, skip, limit),
    enabled: !!portfolioId,
  });
}

const PAGE_SIZE = 100;

/**
 * Hook to fetch transactions with infinite scroll pagination
 */
export function useInfiniteTransactions(portfolioId: number) {
  return useInfiniteQuery({
    queryKey: [...transactionKeys.list(portfolioId), "infinite"],
    queryFn: ({ pageParam = 0 }) => getTransactions(portfolioId, pageParam, PAGE_SIZE),
    enabled: !!portfolioId,
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) => {
      const totalLoaded = allPages.length * PAGE_SIZE;
      const hasMore = totalLoaded < lastPage.pagination.total;
      return hasMore ? totalLoaded : undefined;
    },
  });
}

// -----------------------------------------------------------------------------
// Mutations
// -----------------------------------------------------------------------------

/**
 * Hook to create a transaction
 */
export function useCreateTransaction() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: TransactionCreate) => createTransaction(data),
    onSuccess: (_, { portfolio_id }) => {
      // Invalidate transactions list
      queryClient.invalidateQueries({
        queryKey: transactionKeys.list(portfolio_id),
      });
      // Invalidate portfolio valuation as it will change
      queryClient.invalidateQueries({
        queryKey: portfolioKeys.valuation(portfolio_id),
      });
      toast.success("Transaction added successfully");
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to add transaction");
    },
  });
}

/**
 * Hook to update a transaction
 */
export function useUpdateTransaction() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      portfolioId,
      transactionId,
      data,
    }: {
      portfolioId: number;
      transactionId: number;
      data: TransactionUpdate;
    }) => updateTransaction(portfolioId, transactionId, data),
    onSuccess: (_, { portfolioId }) => {
      queryClient.invalidateQueries({
        queryKey: transactionKeys.list(portfolioId),
      });
      queryClient.invalidateQueries({
        queryKey: portfolioKeys.valuation(portfolioId),
      });
      toast.success("Transaction updated successfully");
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to update transaction");
    },
  });
}

/**
 * Hook to delete a transaction
 */
export function useDeleteTransaction() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      portfolioId,
      transactionId,
    }: {
      portfolioId: number;
      transactionId: number;
    }) => deleteTransaction(portfolioId, transactionId),
    onSuccess: (_, { portfolioId }) => {
      queryClient.invalidateQueries({
        queryKey: transactionKeys.list(portfolioId),
      });
      queryClient.invalidateQueries({
        queryKey: portfolioKeys.valuation(portfolioId),
      });
      toast.success("Transaction deleted successfully");
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to delete transaction");
    },
  });
}

/**
 * Hook to upload transactions from CSV
 *
 * Supports automatic date format detection. If dates are ambiguous,
 * throws AmbiguousDateFormatException which the component should catch
 * and display a format selection dialog.
 */
export function useUploadTransactions() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      portfolioId,
      file,
      dateFormat,
    }: {
      portfolioId: number;
      file: File;
      dateFormat?: UploadDateFormat;
    }) => uploadTransactions(portfolioId, file, dateFormat),
    onSuccess: (result, { portfolioId }) => {
      queryClient.invalidateQueries({
        queryKey: transactionKeys.list(portfolioId),
      });
      queryClient.invalidateQueries({
        queryKey: portfolioKeys.valuation(portfolioId),
      });

      if (result.error_count > 0) {
        toast.warning(
          `Imported ${result.created_count} transactions, ${result.error_count} failed`
        );
      } else {
        toast.success(`Imported ${result.created_count} transactions`);
      }
    },
    onError: (error: Error) => {
      // Don't show toast for ambiguous date format - component will handle it
      if (error instanceof AmbiguousDateFormatException) {
        return;
      }
      toast.error(error.message || "Failed to upload transactions");
    },
  });
}

// Re-export for convenience
export { AmbiguousDateFormatException };
