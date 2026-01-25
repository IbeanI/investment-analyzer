"use client";

import { useState } from "react";
import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import {
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  MoreHorizontal,
  Pencil,
  Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn, formatCurrency, formatDate, formatNumber } from "@/lib/utils";
import { useDeleteTransaction } from "@/hooks/use-transactions";
import type { Transaction, TransactionType } from "@/types/api";

/**
 * Get badge styling for a transaction type.
 * Colors are chosen to match the semantic meaning:
 * - BUY: Green (acquisition, growth)
 * - SELL: Red (disposal, reduction)
 * - DIVIDEND: Blue (passive income)
 * - DEPOSIT: Teal (money coming in)
 * - WITHDRAWAL: Orange (money going out)
 * - FEE: Slate (neutral cost)
 * - TAX: Purple (government)
 */
function getTransactionTypeBadgeClass(type: TransactionType): string {
  const baseClass = "border-transparent";

  switch (type) {
    case "BUY":
      return cn(baseClass, "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400");
    case "SELL":
      return cn(baseClass, "bg-rose-500/15 text-rose-700 dark:text-rose-400");
    case "DIVIDEND":
      return cn(baseClass, "bg-blue-500/15 text-blue-700 dark:text-blue-400");
    case "DEPOSIT":
      return cn(baseClass, "bg-teal-500/15 text-teal-700 dark:text-teal-400");
    case "WITHDRAWAL":
      return cn(baseClass, "bg-amber-500/15 text-amber-700 dark:text-amber-400");
    case "FEE":
      return cn(baseClass, "bg-slate-500/15 text-slate-700 dark:text-slate-400");
    case "TAX":
      return cn(baseClass, "bg-violet-500/15 text-violet-700 dark:text-violet-400");
    default:
      return cn(baseClass, "bg-secondary text-secondary-foreground");
  }
}

interface TransactionListProps {
  transactions: Transaction[];
  portfolioId: number;
  currency: string;
  onEdit?: (transaction: Transaction) => void;
  // Server-side filtering props
  searchValue?: string;
  onSearchChange?: (value: string) => void;
  typeValue?: string;
  onTypeChange?: (value: string) => void;
  availableTypes?: string[];
}

export function TransactionList({
  transactions,
  portfolioId,
  currency: _currency,
  onEdit,
  searchValue = "",
  onSearchChange,
  typeValue = "",
  onTypeChange,
  availableTypes = [],
}: TransactionListProps) {
  const [sorting, setSorting] = useState<SortingState>([
    { id: "date", desc: true },
  ]);
  const [deleteTransaction, setDeleteTransaction] = useState<Transaction | null>(
    null
  );
  const deleteTransactionMutation = useDeleteTransaction();

  const columns: ColumnDef<Transaction>[] = [
    {
      accessorKey: "date",
      header: ({ column }) => (
        <Button
          variant="ghost"
          onClick={() => {
            if (column.getIsSorted() === "desc") {
              column.clearSorting();
            } else {
              column.toggleSorting(column.getIsSorted() === "asc");
            }
          }}
          className="h-auto p-0 hover:bg-transparent"
        >
          Date
          {column.getIsSorted() === "asc" ? (
            <ArrowUp className="ml-2 h-4 w-4" />
          ) : column.getIsSorted() === "desc" ? (
            <ArrowDown className="ml-2 h-4 w-4" />
          ) : (
            <ArrowUpDown className="ml-2 h-4 w-4" />
          )}
        </Button>
      ),
      cell: ({ row }) => formatDate(row.original.date),
    },
    {
      id: "ticker",
      accessorFn: (row) => row.asset?.ticker ?? "",
      header: "Asset",
      cell: ({ row }) => (
        <div>
          <div className="font-medium">{row.original.asset?.ticker}</div>
          <div className="text-sm text-muted-foreground">
            {row.original.asset?.exchange}
          </div>
        </div>
      ),
    },
    {
      accessorKey: "transaction_type",
      header: "Type",
      cell: ({ row }) => (
        <Badge
          variant="outline"
          className={getTransactionTypeBadgeClass(row.original.transaction_type)}
        >
          {row.original.transaction_type}
        </Badge>
      ),
    },
    {
      accessorKey: "quantity",
      header: ({ column }) => (
        <Button
          variant="ghost"
          onClick={() => {
            if (column.getIsSorted() === "desc") {
              column.clearSorting();
            } else {
              column.toggleSorting(column.getIsSorted() === "asc");
            }
          }}
          className="h-auto p-0 hover:bg-transparent"
        >
          Quantity
          {column.getIsSorted() === "asc" ? (
            <ArrowUp className="ml-2 h-4 w-4" />
          ) : column.getIsSorted() === "desc" ? (
            <ArrowDown className="ml-2 h-4 w-4" />
          ) : (
            <ArrowUpDown className="ml-2 h-4 w-4" />
          )}
        </Button>
      ),
      cell: ({ row }) => (
        <div className="text-right">{formatNumber(row.original.quantity, 4)}</div>
      ),
      sortingFn: (rowA, rowB) =>
        parseFloat(rowA.original.quantity) - parseFloat(rowB.original.quantity),
      meta: { align: "right" },
    },
    {
      accessorKey: "price_per_share",
      header: ({ column }) => (
        <Button
          variant="ghost"
          onClick={() => {
            if (column.getIsSorted() === "desc") {
              column.clearSorting();
            } else {
              column.toggleSorting(column.getIsSorted() === "asc");
            }
          }}
          className="h-auto p-0 hover:bg-transparent"
        >
          Price
          {column.getIsSorted() === "asc" ? (
            <ArrowUp className="ml-2 h-4 w-4" />
          ) : column.getIsSorted() === "desc" ? (
            <ArrowDown className="ml-2 h-4 w-4" />
          ) : (
            <ArrowUpDown className="ml-2 h-4 w-4" />
          )}
        </Button>
      ),
      cell: ({ row }) => (
        <div className="text-right">
          {formatCurrency(row.original.price_per_share, row.original.currency)}
        </div>
      ),
      sortingFn: (rowA, rowB) =>
        parseFloat(rowA.original.price_per_share) - parseFloat(rowB.original.price_per_share),
      meta: { align: "right" },
    },
    {
      id: "total",
      header: ({ column }) => (
        <Button
          variant="ghost"
          onClick={() => {
            if (column.getIsSorted() === "desc") {
              column.clearSorting();
            } else {
              column.toggleSorting(column.getIsSorted() === "asc");
            }
          }}
          className="h-auto p-0 hover:bg-transparent"
        >
          Total
          {column.getIsSorted() === "asc" ? (
            <ArrowUp className="ml-2 h-4 w-4" />
          ) : column.getIsSorted() === "desc" ? (
            <ArrowDown className="ml-2 h-4 w-4" />
          ) : (
            <ArrowUpDown className="ml-2 h-4 w-4" />
          )}
        </Button>
      ),
      cell: ({ row }) => {
        const total =
          parseFloat(row.original.quantity) *
          parseFloat(row.original.price_per_share);
        return (
          <div className="text-right font-medium">
            {formatCurrency(total, row.original.currency)}
          </div>
        );
      },
      sortingFn: (rowA, rowB) => {
        const totalA =
          parseFloat(rowA.original.quantity) *
          parseFloat(rowA.original.price_per_share);
        const totalB =
          parseFloat(rowB.original.quantity) *
          parseFloat(rowB.original.price_per_share);
        return totalA - totalB;
      },
      meta: { align: "right" },
    },
    {
      id: "actions",
      cell: ({ row }) => (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" className="h-8 w-8">
              <MoreHorizontal className="h-4 w-4" />
              <span className="sr-only">Actions</span>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={() => onEdit?.(row.original)}>
              <Pencil className="mr-2 h-4 w-4" />
              Edit
            </DropdownMenuItem>
            <DropdownMenuItem
              className="text-destructive focus:text-destructive"
              onClick={() => setDeleteTransaction(row.original)}
            >
              <Trash2 className="mr-2 h-4 w-4" />
              Delete
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      ),
    },
  ];

  const table = useReactTable({
    data: transactions,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    onSortingChange: setSorting,
    state: { sorting },
  });

  const handleDelete = async () => {
    if (deleteTransaction) {
      await deleteTransactionMutation.mutateAsync({
        portfolioId,
        transactionId: deleteTransaction.id,
      });
      setDeleteTransaction(null);
    }
  };

  if (transactions.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-8 text-center">
        No transactions yet. Add your first transaction above.
      </p>
    );
  }

  return (
    <>
      {/* Filters */}
      <div className="mb-4 flex gap-2">
        <Input
          placeholder="Filter by ticker..."
          value={searchValue}
          onChange={(e) => onSearchChange?.(e.target.value)}
          className="max-w-sm"
        />
        <Select
          value={typeValue || "all"}
          onValueChange={(value) => onTypeChange?.(value === "all" ? "" : value)}
        >
          <SelectTrigger className="w-32">
            <SelectValue placeholder="All Types" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Types</SelectItem>
            {availableTypes.map((type) => (
              <SelectItem key={type} value={type}>
                {type.charAt(0) + type.slice(1).toLowerCase()}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Desktop table */}
      <div className="hidden md:block border rounded-lg">
        <table className="w-full">
          <thead className="bg-muted/50">
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id} className="border-b">
                {headerGroup.headers.map((header) => {
                  const align = (header.column.columnDef.meta as { align?: string })?.align;
                  return (
                    <th
                      key={header.id}
                      className={cn(
                        "p-3 font-medium text-muted-foreground",
                        align === "right" ? "text-right" : "text-left"
                      )}
                    >
                      {header.isPlaceholder
                        ? null
                        : flexRender(
                            header.column.columnDef.header,
                            header.getContext()
                          )}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id} className="border-b last:border-0 hover:bg-muted/50">
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="p-3">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile card view */}
      <div className="md:hidden space-y-3">
        {table.getRowModel().rows.map((row) => {
          const transaction = row.original;
          const total =
            parseFloat(transaction.quantity) *
            parseFloat(transaction.price_per_share);

          return (
            <Card key={row.id}>
              <CardContent className="p-4">
                <div className="flex items-start justify-between">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{transaction.asset?.ticker}</span>
                      <Badge
                        variant="outline"
                        className={cn(
                          "text-xs",
                          getTransactionTypeBadgeClass(transaction.transaction_type)
                        )}
                      >
                        {transaction.transaction_type}
                      </Badge>
                    </div>
                    <div className="text-sm text-muted-foreground">
                      {formatDate(transaction.date)}
                    </div>
                    <div className="text-sm">
                      {formatNumber(transaction.quantity, 4)} @{" "}
                      {formatCurrency(
                        transaction.price_per_share,
                        transaction.currency
                      )}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="font-medium">
                      {formatCurrency(total, transaction.currency)}
                    </div>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="sm" className="h-8 mt-1">
                          <MoreHorizontal className="h-4 w-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onClick={() => onEdit?.(transaction)}>
                          <Pencil className="mr-2 h-4 w-4" />
                          Edit
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          className="text-destructive focus:text-destructive"
                          onClick={() => setDeleteTransaction(transaction)}
                        >
                          <Trash2 className="mr-2 h-4 w-4" />
                          Delete
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {/* Delete confirmation */}
      <AlertDialog
        open={deleteTransaction !== null}
        onOpenChange={() => setDeleteTransaction(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Transaction</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete this {deleteTransaction?.asset?.ticker}{" "}
              transaction? This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDelete}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {deleteTransactionMutation.isPending ? "Deleting..." : "Delete"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
