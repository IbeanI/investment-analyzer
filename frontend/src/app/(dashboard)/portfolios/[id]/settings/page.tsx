"use client";

import { use, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { ArrowLeft, Loader2, AlertCircle, Trash2, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import {
  usePortfolio,
  useUpdatePortfolio,
  useDeletePortfolio,
  useSyncStatus,
  useFullResync,
} from "@/hooks/use-portfolios";
import { formatDate } from "@/lib/utils";

// -----------------------------------------------------------------------------
// Constants
// -----------------------------------------------------------------------------

const CURRENCIES = [
  { value: "EUR", label: "Euro (EUR)" },
  { value: "USD", label: "US Dollar (USD)" },
  { value: "GBP", label: "British Pound (GBP)" },
  { value: "CHF", label: "Swiss Franc (CHF)" },
  { value: "JPY", label: "Japanese Yen (JPY)" },
  { value: "CAD", label: "Canadian Dollar (CAD)" },
  { value: "AUD", label: "Australian Dollar (AUD)" },
];

// -----------------------------------------------------------------------------
// Form Schema
// -----------------------------------------------------------------------------

const settingsSchema = z.object({
  name: z
    .string()
    .min(1, "Portfolio name is required")
    .max(100, "Name must be less than 100 characters"),
  currency: z.string().length(3, "Please select a currency"),
});

type SettingsFormData = z.infer<typeof settingsSchema>;

// -----------------------------------------------------------------------------
// Page Component
// -----------------------------------------------------------------------------

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function SettingsPage({ params }: PageProps) {
  const { id } = use(params);
  const portfolioId = parseInt(id, 10);
  const router = useRouter();

  const { data: portfolio, isLoading } = usePortfolio(portfolioId);
  const { data: syncStatus } = useSyncStatus(portfolioId);
  const updatePortfolio = useUpdatePortfolio();
  const deletePortfolio = useDeletePortfolio();
  const fullResync = useFullResync();
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [showResyncDialog, setShowResyncDialog] = useState(false);

  const form = useForm<SettingsFormData>({
    resolver: zodResolver(settingsSchema),
    values: {
      name: portfolio?.name || "",
      currency: portfolio?.currency || "EUR",
    },
  });

  const onSubmit = async (data: SettingsFormData) => {
    try {
      await updatePortfolio.mutateAsync({
        id: portfolioId,
        data,
      });
    } catch {
      // Error handled by mutation
    }
  };

  const handleDelete = async () => {
    try {
      await deletePortfolio.mutateAsync(portfolioId);
      router.push("/portfolios");
    } catch {
      // Error handled by mutation
    }
  };

  if (isLoading) {
    return (
      <div className="space-y-6 max-w-2xl">
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
      <div className="space-y-6 max-w-2xl">
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
    <div className="space-y-6 max-w-2xl">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="icon" asChild className="-ml-2">
          <Link href={`/portfolios/${portfolioId}`}>
            <ArrowLeft className="h-4 w-4" />
          </Link>
        </Button>
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
          <p className="text-muted-foreground">{portfolio.name}</p>
        </div>
      </div>

      {/* General Settings */}
      <Card>
        <CardHeader>
          <CardTitle>General</CardTitle>
          <CardDescription>
            Update your portfolio name and base currency
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Form {...form}>
            <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
              <FormField
                control={form.control}
                name="name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Portfolio Name</FormLabel>
                    <FormControl>
                      <Input {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="currency"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Base Currency</FormLabel>
                    <Select
                      onValueChange={field.onChange}
                      defaultValue={field.value}
                    >
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue placeholder="Select a currency" />
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
                    <FormDescription>
                      All values will be converted to this currency
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <Button type="submit" disabled={updatePortfolio.isPending}>
                {updatePortfolio.isPending && (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                )}
                Save Changes
              </Button>
            </form>
          </Form>
        </CardContent>
      </Card>

      {/* Portfolio Info */}
      <Card>
        <CardHeader>
          <CardTitle>Information</CardTitle>
          <CardDescription>Portfolio metadata and statistics</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <p className="text-sm text-muted-foreground">Created</p>
              <p className="font-medium">{formatDate(portfolio.created_at)}</p>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">Last Updated</p>
              <p className="font-medium">{formatDate(portfolio.updated_at)}</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Data Management */}
      <Card>
        <CardHeader>
          <CardTitle>Data Management</CardTitle>
          <CardDescription>
            Manage market data synchronization for this portfolio
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <p className="font-medium">Full Re-sync</p>
              <p className="text-sm text-muted-foreground">
                Re-fetch all historical market data from scratch. Use if you suspect
                missing or incorrect prices.
              </p>
              {syncStatus?.last_full_sync && (
                <p className="text-xs text-muted-foreground mt-1">
                  Last full re-sync: {formatDate(syncStatus.last_full_sync)}
                </p>
              )}
            </div>
            <AlertDialog open={showResyncDialog} onOpenChange={setShowResyncDialog}>
              <AlertDialogTrigger asChild>
                <Button variant="outline" disabled={fullResync.isPending}>
                  {fullResync.isPending ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Re-syncing...
                    </>
                  ) : (
                    <>
                      <RefreshCw className="mr-2 h-4 w-4" />
                      Full Re-sync
                    </>
                  )}
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Perform Full Re-sync?</AlertDialogTitle>
                  <AlertDialogDescription>
                    This will re-fetch all historical market data for this portfolio.
                    This operation may take several minutes and can only be performed
                    once per hour.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction
                    onClick={() => {
                      fullResync.mutate(portfolioId);
                      setShowResyncDialog(false);
                    }}
                  >
                    Start Re-sync
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </div>
        </CardContent>
      </Card>

      {/* Danger Zone */}
      <Card className="border-destructive/50">
        <CardHeader>
          <CardTitle className="text-destructive">Danger Zone</CardTitle>
          <CardDescription>
            Irreversible actions that affect your portfolio
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <p className="font-medium">Delete Portfolio</p>
              <p className="text-sm text-muted-foreground">
                Permanently delete this portfolio and all its transactions
              </p>
            </div>
            <AlertDialog open={showDeleteDialog} onOpenChange={setShowDeleteDialog}>
              <AlertDialogTrigger asChild>
                <Button variant="destructive">
                  <Trash2 className="mr-2 h-4 w-4" />
                  Delete Portfolio
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Are you absolutely sure?</AlertDialogTitle>
                  <AlertDialogDescription>
                    This action cannot be undone. This will permanently delete{" "}
                    <span className="font-medium">{portfolio.name}</span> and all
                    its transactions, valuations, and analytics data.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction
                    onClick={handleDelete}
                    className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                  >
                    {deletePortfolio.isPending ? (
                      <>
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        Deleting...
                      </>
                    ) : (
                      "Delete Portfolio"
                    )}
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
