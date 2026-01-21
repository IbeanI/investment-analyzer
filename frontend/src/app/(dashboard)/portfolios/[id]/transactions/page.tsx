"use client";

import { use, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Plus, Upload, FileSpreadsheet } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { AlertCircle } from "lucide-react";
import { TransactionForm, TransactionList, CsvUpload } from "@/components/forms";
import { usePortfolio } from "@/hooks/use-portfolios";
import { useTransactions } from "@/hooks/use-transactions";
import type { Transaction } from "@/types/api";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function TransactionsPage({ params }: PageProps) {
  const { id } = use(params);
  const portfolioId = parseInt(id, 10);

  const { data: portfolio, isLoading: portfolioLoading } = usePortfolio(portfolioId);
  const { data: transactionsData, isLoading: transactionsLoading } =
    useTransactions(portfolioId);

  const [showAddForm, setShowAddForm] = useState(false);
  const [editTransaction, setEditTransaction] = useState<Transaction | null>(null);

  const transactions = transactionsData?.items || [];

  if (portfolioLoading) {
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-4">
          <Skeleton className="h-8 w-8" />
          <Skeleton className="h-8 w-48" />
        </div>
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (!portfolio) {
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
          <AlertDescription>Portfolio not found</AlertDescription>
        </Alert>
      </div>
    );
  }

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
            <h1 className="text-2xl font-bold tracking-tight">Transactions</h1>
            <p className="text-muted-foreground">{portfolio.name}</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* CSV Upload Dialog */}
          <Dialog>
            <DialogTrigger asChild>
              <Button variant="outline">
                <Upload className="mr-2 h-4 w-4" />
                <span className="hidden sm:inline">Import CSV</span>
              </Button>
            </DialogTrigger>
            <DialogContent className="max-w-lg">
              <DialogHeader>
                <DialogTitle>Import Transactions</DialogTitle>
                <DialogDescription>
                  Upload a CSV file to import multiple transactions at once.
                </DialogDescription>
              </DialogHeader>
              <CsvUpload portfolioId={portfolioId} />
            </DialogContent>
          </Dialog>

          {/* Add Transaction Sheet */}
          <Sheet open={showAddForm} onOpenChange={setShowAddForm}>
            <SheetTrigger asChild>
              <Button>
                <Plus className="mr-2 h-4 w-4" />
                <span className="hidden sm:inline">Add Transaction</span>
              </Button>
            </SheetTrigger>
            <SheetContent className="w-full sm:max-w-lg overflow-y-auto">
              <SheetHeader>
                <SheetTitle>Add Transaction</SheetTitle>
                <SheetDescription>
                  Record a new buy or sell transaction for {portfolio.name}.
                </SheetDescription>
              </SheetHeader>
              <div className="mt-6">
                <TransactionForm
                  portfolioId={portfolioId}
                  portfolioCurrency={portfolio.currency}
                  onSuccess={() => setShowAddForm(false)}
                  onCancel={() => setShowAddForm(false)}
                />
              </div>
            </SheetContent>
          </Sheet>
        </div>
      </div>

      {/* Edit Transaction Sheet */}
      <Sheet
        open={editTransaction !== null}
        onOpenChange={(open) => !open && setEditTransaction(null)}
      >
        <SheetContent className="w-full sm:max-w-lg overflow-y-auto">
          <SheetHeader>
            <SheetTitle>Edit Transaction</SheetTitle>
            <SheetDescription>
              Update transaction details for {editTransaction?.asset.ticker}.
            </SheetDescription>
          </SheetHeader>
          {editTransaction && (
            <div className="mt-6">
              <TransactionForm
                portfolioId={portfolioId}
                portfolioCurrency={portfolio.currency}
                transaction={editTransaction}
                onSuccess={() => setEditTransaction(null)}
                onCancel={() => setEditTransaction(null)}
              />
            </div>
          )}
        </SheetContent>
      </Sheet>

      {/* Content */}
      <Card>
        <CardHeader>
          <CardTitle>Transaction History</CardTitle>
          <CardDescription>
            {transactions.length} transaction{transactions.length !== 1 ? "s" : ""}{" "}
            recorded
          </CardDescription>
        </CardHeader>
        <CardContent>
          {transactionsLoading ? (
            <div className="space-y-3">
              {[1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-16 w-full" />
              ))}
            </div>
          ) : (
            <TransactionList
              transactions={transactions}
              portfolioId={portfolioId}
              currency={portfolio.currency}
              onEdit={setEditTransaction}
            />
          )}
        </CardContent>
      </Card>

      {/* Quick help */}
      {transactions.length === 0 && (
        <Card className="bg-muted/50">
          <CardContent className="pt-6">
            <div className="flex items-start gap-4">
              <FileSpreadsheet className="h-8 w-8 text-muted-foreground shrink-0" />
              <div>
                <h3 className="font-medium mb-1">Getting Started</h3>
                <p className="text-sm text-muted-foreground">
                  Add transactions manually using the button above, or import them
                  from a CSV file exported from your broker. After adding
                  transactions, sync market data to see your portfolio valuation.
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
