"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getTransactions,
  createTransaction,
  updateTransaction,
  deleteTransaction,
  uploadTransactions,
} from "@/lib/api/transactions";
import type { TransactionCreate, TransactionUpdate } from "@/types/api";
import { toast } from "sonner";
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
 */
export function useUploadTransactions() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      portfolioId,
      file,
    }: {
      portfolioId: number;
      file: File;
    }) => uploadTransactions(portfolioId, file),
    onSuccess: (result, { portfolioId }) => {
      queryClient.invalidateQueries({
        queryKey: transactionKeys.list(portfolioId),
      });
      queryClient.invalidateQueries({
        queryKey: portfolioKeys.valuation(portfolioId),
      });

      if (result.error_count > 0) {
        toast.warning(
          `Imported ${result.success_count} transactions, ${result.error_count} failed`
        );
      } else {
        toast.success(`Imported ${result.success_count} transactions`);
      }
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to upload transactions");
    },
  });
}
