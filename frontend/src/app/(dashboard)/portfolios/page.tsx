"use client";

import { useState } from "react";
import Link from "next/link";
import { Plus, Briefcase, LayoutGrid, List } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PortfolioCard, PortfolioCardSkeleton } from "@/components/portfolio";
import { EmptyState } from "@/components/shared";
import { usePortfolios, useDeletePortfolio } from "@/hooks/use-portfolios";
import { formatDate } from "@/lib/utils";

export default function PortfoliosPage() {
  const { data, isLoading, error } = usePortfolios();
  const deletePortfolio = useDeletePortfolio();
  const [view, setView] = useState<"grid" | "list">("grid");
  const [deleteId, setDeleteId] = useState<number | null>(null);

  const portfolios = data?.items || [];

  const handleDelete = async () => {
    if (deleteId) {
      await deletePortfolio.mutateAsync(deleteId);
      setDeleteId(null);
    }
  };

  if (error) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold tracking-tight">Portfolios</h1>
        </div>
        <Card>
          <CardHeader>
            <CardTitle className="text-destructive">Error</CardTitle>
            <CardDescription>Failed to load portfolios</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              {error instanceof Error ? error.message : "An error occurred"}
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Portfolios</h1>
          <p className="text-muted-foreground">
            Manage your investment portfolios
          </p>
        </div>
        <div className="flex items-center gap-2">
          {/* View toggle - hidden on mobile */}
          <Tabs
            value={view}
            onValueChange={(v) => setView(v as "grid" | "list")}
            className="hidden sm:block"
          >
            <TabsList>
              <TabsTrigger value="grid">
                <LayoutGrid className="h-4 w-4" />
              </TabsTrigger>
              <TabsTrigger value="list">
                <List className="h-4 w-4" />
              </TabsTrigger>
            </TabsList>
          </Tabs>
          <Button asChild>
            <Link href="/portfolios/new">
              <Plus className="mr-2 h-4 w-4" />
              New Portfolio
            </Link>
          </Button>
        </div>
      </div>

      {/* Content */}
      {isLoading ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3].map((i) => (
            <PortfolioCardSkeleton key={i} />
          ))}
        </div>
      ) : portfolios.length === 0 ? (
        <EmptyState
          icon={<Briefcase className="h-8 w-8 text-muted-foreground" />}
          title="No portfolios yet"
          description="Create your first portfolio to start tracking your investments and analyzing performance."
          action={
            <Button asChild>
              <Link href="/portfolios/new">
                <Plus className="mr-2 h-4 w-4" />
                Create Portfolio
              </Link>
            </Button>
          }
        />
      ) : view === "grid" ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {portfolios.map((portfolio) => (
            <PortfolioCard
              key={portfolio.id}
              portfolio={portfolio}
              onDelete={setDeleteId}
            />
          ))}
        </div>
      ) : (
        <Card>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b">
                  <th className="p-4 text-left font-medium text-muted-foreground">
                    Name
                  </th>
                  <th className="p-4 text-left font-medium text-muted-foreground">
                    Currency
                  </th>
                  <th className="p-4 text-left font-medium text-muted-foreground hidden sm:table-cell">
                    Created
                  </th>
                  <th className="p-4 text-left font-medium text-muted-foreground hidden md:table-cell">
                    Updated
                  </th>
                  <th className="p-4 text-right font-medium text-muted-foreground">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody>
                {portfolios.map((portfolio) => (
                  <tr key={portfolio.id} className="border-b last:border-0">
                    <td className="p-4">
                      <Link
                        href={`/portfolios/${portfolio.id}`}
                        className="font-medium hover:underline"
                      >
                        {portfolio.name}
                      </Link>
                    </td>
                    <td className="p-4">{portfolio.currency}</td>
                    <td className="p-4 hidden sm:table-cell text-muted-foreground">
                      {formatDate(portfolio.created_at)}
                    </td>
                    <td className="p-4 hidden md:table-cell text-muted-foreground">
                      {formatDate(portfolio.updated_at)}
                    </td>
                    <td className="p-4 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <Button variant="outline" size="sm" asChild>
                          <Link href={`/portfolios/${portfolio.id}`}>View</Link>
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          className="text-destructive hover:text-destructive"
                          onClick={() => setDeleteId(portfolio.id)}
                        >
                          Delete
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* Delete confirmation dialog */}
      <AlertDialog open={deleteId !== null} onOpenChange={() => setDeleteId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Portfolio</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete this portfolio? This action cannot
              be undone and will permanently delete all transactions and data
              associated with this portfolio.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDelete}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {deletePortfolio.isPending ? "Deleting..." : "Delete"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
