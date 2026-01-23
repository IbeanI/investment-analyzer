"use client";

import { useState, useMemo } from "react";
import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { ArrowUpDown, ArrowUp, ArrowDown, Info } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { formatCurrency, formatPercentage, formatNumber } from "@/lib/utils";
import type { HoldingValuation } from "@/types/api";

interface HoldingsTableProps {
  holdings: HoldingValuation[];
  currency: string;
}

export function HoldingsTable({ holdings, currency }: HoldingsTableProps) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [tickerFilter, setTickerFilter] = useState("");

  const filteredHoldings = useMemo(() => {
    if (!tickerFilter) return holdings;
    return holdings.filter((holding) =>
      holding.ticker.toLowerCase().includes(tickerFilter.toLowerCase())
    );
  }, [holdings, tickerFilter]);

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
            {row.original.asset_name}
          </div>
        </div>
      ),
    },
    {
      accessorKey: "exchange",
      header: "Exchange",
      cell: ({ row }) => (
        <div>{row.original.exchange || "—"}</div>
      ),
    },
    {
      accessorKey: "quantity",
      header: ({ column }) => (
        <div className="flex justify-end">
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
            {column.getIsSorted() === "asc" ? (
              <ArrowUp className="mr-2 h-4 w-4" />
            ) : column.getIsSorted() === "desc" ? (
              <ArrowDown className="mr-2 h-4 w-4" />
            ) : (
              <ArrowUpDown className="mr-2 h-4 w-4" />
            )}
            Quantity
          </Button>
        </div>
      ),
      cell: ({ row }) => (
        <div className="text-right">
          {formatNumber(row.original.quantity, 4)}
        </div>
      ),
    },
    {
      accessorKey: "current_value.price_per_share",
      header: ({ column }) => (
        <div className="flex justify-end">
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
            {column.getIsSorted() === "asc" ? (
              <ArrowUp className="mr-2 h-4 w-4" />
            ) : column.getIsSorted() === "desc" ? (
              <ArrowDown className="mr-2 h-4 w-4" />
            ) : (
              <ArrowUpDown className="mr-2 h-4 w-4" />
            )}
            Price
          </Button>
        </div>
      ),
      cell: ({ row }) => (
        <div className="text-right">
          {row.original.current_value.price_per_share
            ? formatCurrency(
                row.original.current_value.price_per_share,
                row.original.current_value.local_currency || "USD"
              )
            : "—"}
        </div>
      ),
      sortingFn: (rowA, rowB) => {
        const a = parseFloat(rowA.original.current_value.price_per_share || "0");
        const b = parseFloat(rowB.original.current_value.price_per_share || "0");
        return a - b;
      },
    },
    {
      accessorKey: "cost_basis.avg_cost_per_share",
      header: ({ column }) => (
        <div className="flex items-center justify-end gap-1">
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
            {column.getIsSorted() === "asc" ? (
              <ArrowUp className="mr-2 h-4 w-4" />
            ) : column.getIsSorted() === "desc" ? (
              <ArrowDown className="mr-2 h-4 w-4" />
            ) : (
              <ArrowUpDown className="mr-2 h-4 w-4" />
            )}
            BEP
          </Button>
          <Tooltip>
            <TooltipTrigger asChild>
              <Info className="h-4 w-4 text-muted-foreground cursor-help" />
            </TooltipTrigger>
            <TooltipContent className="max-w-xs">
              <p className="font-semibold">Break Even Price</p>
              <p className="text-sm mt-1">
                The weighted average price for each unit of your current position.
              </p>
              <p className="text-sm mt-2 text-muted-foreground">
                Note: The value is displayed for information purposes only. In some cases it may not be accurate, for instance if fees are excluded from calculations, there was a corporate action or a portfolio transfer that affected your position.
              </p>
            </TooltipContent>
          </Tooltip>
        </div>
      ),
      cell: ({ row }) => (
        <div className="text-right">
          {row.original.cost_basis.avg_cost_per_share
            ? formatNumber(row.original.cost_basis.avg_cost_per_share, 2)
            : "—"}
        </div>
      ),
      sortingFn: (rowA, rowB) => {
        const a = parseFloat(rowA.original.cost_basis.avg_cost_per_share || "0");
        const b = parseFloat(rowB.original.cost_basis.avg_cost_per_share || "0");
        return a - b;
      },
    },
    {
      accessorKey: "current_value.portfolio_amount",
      header: ({ column }) => (
        <div className="flex justify-end">
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
            {column.getIsSorted() === "asc" ? (
              <ArrowUp className="mr-2 h-4 w-4" />
            ) : column.getIsSorted() === "desc" ? (
              <ArrowDown className="mr-2 h-4 w-4" />
            ) : (
              <ArrowUpDown className="mr-2 h-4 w-4" />
            )}
            Value
          </Button>
        </div>
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
        <div className="flex justify-end">
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
            {column.getIsSorted() === "asc" ? (
              <ArrowUp className="mr-2 h-4 w-4" />
            ) : column.getIsSorted() === "desc" ? (
              <ArrowDown className="mr-2 h-4 w-4" />
            ) : (
              <ArrowUpDown className="mr-2 h-4 w-4" />
            )}
            P/L
          </Button>
        </div>
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
    data: filteredHoldings,
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
      {/* Filter input */}
      <div className="mb-4">
        <Input
          placeholder="Filter by ticker"
          value={tickerFilter}
          onChange={(e) => setTickerFilter(e.target.value)}
          className="max-w-xs"
        />
      </div>

      {/* Desktop table */}
      <div className="hidden md:block overflow-x-auto border rounded-lg">
        <table className="w-full">
          <thead className="bg-muted/50">
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id} className="border-b">
                {headerGroup.headers.map((header) => (
                  <th
                    key={header.id}
                    className="p-3 text-left font-medium text-muted-foreground"
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
        {filteredHoldings.map((holding) => {
          const pnlPercent = holding.pnl.unrealized_percentage;
          const pnlAmount = holding.pnl.unrealized_amount;
          const numericPercent = pnlPercent ? parseFloat(pnlPercent) : null;

          return (
            <Card key={holding.asset_id}>
              <CardContent className="p-4">
                <div className="flex items-start justify-between mb-3">
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
                      {holding.asset_name}
                    </div>
                    {holding.exchange && (
                      <div className="text-sm text-muted-foreground">
                        {holding.exchange}
                      </div>
                    )}
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
                      {pnlAmount && (
                        <span className="ml-1 text-xs">
                          ({formatCurrency(pnlAmount, currency)})
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-2 text-sm">
                  <div>
                    <span className="text-muted-foreground">Quantity:</span>{" "}
                    {formatNumber(holding.quantity, 4)}
                  </div>
                  <div>
                    <span className="text-muted-foreground">Price:</span>{" "}
                    {holding.current_value.price_per_share
                      ? formatCurrency(
                          holding.current_value.price_per_share,
                          holding.current_value.local_currency || "USD"
                        )
                      : "—"}
                  </div>
                  <div>
                    <span className="text-muted-foreground">BEP:</span>{" "}
                    {holding.cost_basis.avg_cost_per_share
                      ? formatNumber(holding.cost_basis.avg_cost_per_share, 2)
                      : "—"}
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
