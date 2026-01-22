"use client";

import { useEffect, useMemo } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Loader2, Calculator } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Card, CardContent } from "@/components/ui/card";
import { useCreateTransaction, useUpdateTransaction } from "@/hooks/use-transactions";
import { formatCurrency, formatDateForApi } from "@/lib/utils";
import type { Transaction, TransactionType } from "@/types/api";

// -----------------------------------------------------------------------------
// Constants
// -----------------------------------------------------------------------------

const TRANSACTION_TYPES: { value: TransactionType; label: string }[] = [
  { value: "BUY", label: "Buy" },
  { value: "SELL", label: "Sell" },
];

const CURRENCIES = [
  { value: "EUR", label: "EUR" },
  { value: "USD", label: "USD" },
  { value: "GBP", label: "GBP" },
  { value: "CHF", label: "CHF" },
  { value: "JPY", label: "JPY" },
  { value: "CAD", label: "CAD" },
  { value: "AUD", label: "AUD" },
];

// -----------------------------------------------------------------------------
// Form Schema
// -----------------------------------------------------------------------------

const transactionSchema = z.object({
  ticker: z
    .string()
    .min(1, "Ticker is required")
    .max(10, "Ticker must be 10 characters or less")
    .transform((val) => val.toUpperCase()),
  exchange: z
    .string()
    .min(1, "Exchange is required")
    .max(10, "Exchange must be 10 characters or less"),
  transaction_type: z.enum(["BUY", "SELL"]),
  date: z.string().min(1, "Date is required"),
  quantity: z
    .string()
    .min(1, "Quantity is required")
    .refine((val) => !isNaN(parseFloat(val)) && parseFloat(val) > 0, {
      message: "Quantity must be a positive number",
    }),
  price_per_share: z
    .string()
    .min(1, "Price is required")
    .refine((val) => !isNaN(parseFloat(val)) && parseFloat(val) > 0, {
      message: "Price must be a positive number",
    }),
  currency: z.string().length(3, "Select a currency"),
  fee: z
    .string()
    .optional()
    .refine(
      (val) => !val || (!isNaN(parseFloat(val)) && parseFloat(val) >= 0),
      { message: "Fee must be a non-negative number" }
    ),
});

type TransactionFormData = z.infer<typeof transactionSchema>;

// -----------------------------------------------------------------------------
// Component
// -----------------------------------------------------------------------------

interface TransactionFormProps {
  portfolioId: number;
  portfolioCurrency: string;
  transaction?: Transaction;
  onSuccess?: () => void;
  onCancel?: () => void;
}

export function TransactionForm({
  portfolioId,
  portfolioCurrency,
  transaction,
  onSuccess,
  onCancel,
}: TransactionFormProps) {
  const createTransaction = useCreateTransaction();
  const updateTransaction = useUpdateTransaction();
  const isEditing = !!transaction;

  const form = useForm<TransactionFormData>({
    resolver: zodResolver(transactionSchema),
    defaultValues: {
      ticker: transaction?.asset.ticker || "",
      exchange: transaction?.asset.exchange || "",
      transaction_type: (transaction?.transaction_type as "BUY" | "SELL") || "BUY",
      date: transaction?.date
        ? transaction.date.split("T")[0]
        : formatDateForApi(new Date()),
      quantity: transaction?.quantity || "",
      price_per_share: transaction?.price_per_share || "",
      currency: transaction?.currency || portfolioCurrency,
      fee: transaction?.fee || "",
    },
  });

  const watchQuantity = form.watch("quantity");
  const watchPrice = form.watch("price_per_share");
  const watchFee = form.watch("fee");
  const watchCurrency = form.watch("currency");

  // Calculate totals
  const totals = useMemo(() => {
    const quantity = parseFloat(watchQuantity) || 0;
    const price = parseFloat(watchPrice) || 0;
    const fee = parseFloat(watchFee || "0") || 0;
    const subtotal = quantity * price;
    const total = subtotal + fee;

    return {
      subtotal,
      fee,
      total,
    };
  }, [watchQuantity, watchPrice, watchFee]);

  const onSubmit = async (data: TransactionFormData) => {
    try {
      if (isEditing && transaction) {
        await updateTransaction.mutateAsync({
          portfolioId,
          transactionId: transaction.id,
          data: {
            date: data.date,
            quantity: data.quantity,
            price_per_share: data.price_per_share,
            currency: data.currency,
            fee: data.fee || undefined,
          },
        });
      } else {
        await createTransaction.mutateAsync({
          portfolio_id: portfolioId,
          ticker: data.ticker,
          exchange: data.exchange,
          transaction_type: data.transaction_type,
          date: data.date,
          quantity: data.quantity,
          price_per_share: data.price_per_share,
          currency: data.currency,
          fee: data.fee || undefined,
        });
      }
      form.reset();
      onSuccess?.();
    } catch {
      // Error is handled by the mutation
    }
  };

  const isPending = createTransaction.isPending || updateTransaction.isPending;

  return (
    <Form {...form}>
      <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
        <div className="grid gap-4 sm:grid-cols-2">
          {/* Ticker */}
          <FormField
            control={form.control}
            name="ticker"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Ticker</FormLabel>
                <FormControl>
                  <Input
                    placeholder="AAPL"
                    {...field}
                    disabled={isEditing}
                    className="uppercase"
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          {/* Exchange */}
          <FormField
            control={form.control}
            name="exchange"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Exchange</FormLabel>
                <FormControl>
                  <Input
                    placeholder="NASDAQ"
                    {...field}
                    disabled={isEditing}
                    className="uppercase"
                  />
                </FormControl>
                <FormDescription>Leave empty for auto-detect</FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          {/* Transaction Type */}
          <FormField
            control={form.control}
            name="transaction_type"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Type</FormLabel>
                <Select
                  onValueChange={field.onChange}
                  defaultValue={field.value}
                  disabled={isEditing}
                >
                  <FormControl>
                    <SelectTrigger>
                      <SelectValue placeholder="Select type" />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent>
                    {TRANSACTION_TYPES.map((type) => (
                      <SelectItem key={type.value} value={type.value}>
                        {type.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <FormMessage />
              </FormItem>
            )}
          />

          {/* Date */}
          <FormField
            control={form.control}
            name="date"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Date</FormLabel>
                <FormControl>
                  <Input type="date" {...field} max={formatDateForApi(new Date())} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        </div>

        <div className="grid gap-4 sm:grid-cols-3">
          {/* Quantity */}
          <FormField
            control={form.control}
            name="quantity"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Quantity</FormLabel>
                <FormControl>
                  <Input
                    type="number"
                    step="any"
                    min="0"
                    placeholder="100"
                    {...field}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          {/* Price */}
          <FormField
            control={form.control}
            name="price_per_share"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Price per Share</FormLabel>
                <FormControl>
                  <Input
                    type="number"
                    step="any"
                    min="0"
                    placeholder="150.00"
                    {...field}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          {/* Currency */}
          <FormField
            control={form.control}
            name="currency"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Currency</FormLabel>
                <Select onValueChange={field.onChange} defaultValue={field.value}>
                  <FormControl>
                    <SelectTrigger>
                      <SelectValue placeholder="Currency" />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent>
                    {CURRENCIES.map((currency) => (
                      <SelectItem key={currency.value} value={currency.value}>
                        {currency.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <FormMessage />
              </FormItem>
            )}
          />
        </div>

        {/* Fee */}
        <FormField
          control={form.control}
          name="fee"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Fee (optional)</FormLabel>
              <FormControl>
                <Input
                  type="number"
                  step="any"
                  min="0"
                  placeholder="0.00"
                  {...field}
                />
              </FormControl>
              <FormDescription>
                Broker commission or transaction fee
              </FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />

        {/* Totals Card */}
        {(totals.subtotal > 0 || totals.fee > 0) && (
          <Card className="bg-muted/50">
            <CardContent className="pt-4">
              <div className="flex items-center gap-2 mb-3">
                <Calculator className="h-4 w-4 text-muted-foreground" />
                <span className="text-sm font-medium">Transaction Summary</span>
              </div>
              <div className="space-y-1 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Subtotal</span>
                  <span>{formatCurrency(totals.subtotal, watchCurrency)}</span>
                </div>
                {totals.fee > 0 && (
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Fee</span>
                    <span>{formatCurrency(totals.fee, watchCurrency)}</span>
                  </div>
                )}
                <div className="flex justify-between pt-2 border-t font-medium">
                  <span>Total</span>
                  <span>{formatCurrency(totals.total, watchCurrency)}</span>
                </div>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Actions */}
        <div className="flex gap-3">
          {onCancel && (
            <Button type="button" variant="outline" onClick={onCancel}>
              Cancel
            </Button>
          )}
          <Button type="submit" disabled={isPending} className="flex-1 sm:flex-none">
            {isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {isEditing ? "Update Transaction" : "Add Transaction"}
          </Button>
        </div>
      </form>
    </Form>
  );
}
