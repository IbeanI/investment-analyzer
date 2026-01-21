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
import { ArrowUpDown, ArrowUp, ArrowDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatCurrency, formatPercentage, formatNumber } from "@/lib/utils";
import type { HoldingValuation } from "@/types/api";

interface HoldingsTableProps {
  holdings: HoldingValuation[];
  currency: string;
}

export function HoldingsTable({ holdings, currency }: HoldingsTableProps) {
  const [sorting, setSorting] = useState<SortingState>([]);

  const columns: ColumnDef<HoldingValuation>[] = [
    {
      accessorKey: "ticker",
      header: "Asset",
      cell: ({ row }) => (
        <div>
          <div className="font-medium flex items-center gap-2">
            {row.original.ticker}
            {row.original.price_is_synthetic && (
              <Badge variant="outline" className="text-xs">
                Proxy
              </Badge>
            )}
          </div>
          <div className="text-sm text-muted-foreground">
            {row.original.asset_name || row.original.exchange}
          </div>
        </div>
      ),
    },
    {
      accessorKey: "quantity",
      header: ({ column }) => (
        <Button
          variant="ghost"
          onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          className="h-auto p-0 hover:bg-transparent"
        >
          Shares
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
          {formatNumber(row.original.quantity, 4)}
        </div>
      ),
    },
    {
      accessorKey: "current_value.portfolio_amount",
      header: ({ column }) => (
        <Button
          variant="ghost"
          onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          className="h-auto p-0 hover:bg-transparent"
        >
          Value
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
          {row.original.current_value.portfolio_amount
            ? formatCurrency(row.original.current_value.portfolio_amount, currency)
            : "—"}
        </div>
      ),
      sortingFn: (rowA, rowB) => {
        const a = parseFloat(rowA.original.current_value.portfolio_amount || "0");
        const b = parseFloat(rowB.original.current_value.portfolio_amount || "0");
        return a - b;
      },
    },
    {
      accessorKey: "pnl.unrealized_percentage",
      header: ({ column }) => (
        <Button
          variant="ghost"
          onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          className="h-auto p-0 hover:bg-transparent"
        >
          P&L
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
        const pnlPercent = row.original.pnl.unrealized_percentage;
        const pnlAmount = row.original.pnl.unrealized_amount;
        const numericPercent = pnlPercent ? parseFloat(pnlPercent) : null;

        return (
          <div
            className={`text-right ${
              numericPercent && numericPercent > 0
                ? "text-green-600 dark:text-green-500"
                : numericPercent && numericPercent < 0
                  ? "text-red-600 dark:text-red-500"
                  : ""
            }`}
          >
            <div>{pnlPercent ? formatPercentage(pnlPercent) : "—"}</div>
            {pnlAmount && (
              <div className="text-xs text-muted-foreground">
                {formatCurrency(pnlAmount, currency)}
              </div>
            )}
          </div>
        );
      },
      sortingFn: (rowA, rowB) => {
        const a = parseFloat(rowA.original.pnl.unrealized_percentage || "0");
        const b = parseFloat(rowB.original.pnl.unrealized_percentage || "0");
        return a - b;
      },
    },
  ];

  const table = useReactTable({
    data: holdings,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    onSortingChange: setSorting,
    state: { sorting },
  });

  if (holdings.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-4 text-center">
        No holdings yet. Add transactions to see your holdings.
      </p>
    );
  }

  return (
    <>
      {/* Desktop table */}
      <div className="hidden md:block overflow-x-auto">
        <table className="w-full">
          <thead>
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id} className="border-b">
                {headerGroup.headers.map((header) => (
                  <th
                    key={header.id}
                    className="pb-3 text-left font-medium text-muted-foreground"
                  >
                    {header.isPlaceholder
                      ? null
                      : flexRender(
                          header.column.columnDef.header,
                          header.getContext()
                        )}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id} className="border-b last:border-0">
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="py-3">
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
        {holdings.map((holding) => {
          const pnlPercent = holding.pnl.unrealized_percentage;
          const numericPercent = pnlPercent ? parseFloat(pnlPercent) : null;

          return (
            <Card key={holding.asset_id}>
              <CardContent className="p-4">
                <div className="flex items-start justify-between">
                  <div>
                    <div className="font-medium flex items-center gap-2">
                      {holding.ticker}
                      {holding.price_is_synthetic && (
                        <Badge variant="outline" className="text-xs">
                          Proxy
                        </Badge>
                      )}
                    </div>
                    <div className="text-sm text-muted-foreground">
                      {holding.asset_name || holding.exchange}
                    </div>
                    <div className="text-sm text-muted-foreground mt-1">
                      {formatNumber(holding.quantity, 4)} shares
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="font-medium">
                      {holding.current_value.portfolio_amount
                        ? formatCurrency(
                            holding.current_value.portfolio_amount,
                            currency
                          )
                        : "—"}
                    </div>
                    <div
                      className={`text-sm ${
                        numericPercent && numericPercent > 0
                          ? "text-green-600 dark:text-green-500"
                          : numericPercent && numericPercent < 0
                            ? "text-red-600 dark:text-red-500"
                            : "text-muted-foreground"
                      }`}
                    >
                      {pnlPercent ? formatPercentage(pnlPercent) : "—"}
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </>
  );
}
