"use client";

import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { ArrowLeft, Loader2 } from "lucide-react";
import Link from "next/link";

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
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useCreatePortfolio } from "@/hooks/use-portfolios";

// Need to add Select component to shadcn
// For now, we'll install it

// -----------------------------------------------------------------------------
// Form Schema
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

const createPortfolioSchema = z.object({
  name: z
    .string()
    .min(1, "Portfolio name is required")
    .max(100, "Name must be less than 100 characters"),
  currency: z.string().length(3, "Please select a currency"),
});

type CreatePortfolioFormData = z.infer<typeof createPortfolioSchema>;

// -----------------------------------------------------------------------------
// Create Portfolio Page
// -----------------------------------------------------------------------------

export default function CreatePortfolioPage() {
  const router = useRouter();
  const createPortfolio = useCreatePortfolio();

  const form = useForm<CreatePortfolioFormData>({
    resolver: zodResolver(createPortfolioSchema),
    defaultValues: {
      name: "",
      currency: "EUR",
    },
  });

  const onSubmit = async (data: CreatePortfolioFormData) => {
    try {
      const portfolio = await createPortfolio.mutateAsync(data);
      router.push(`/portfolios/${portfolio.id}`);
    } catch {
      // Error is handled by the mutation
    }
  };

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      {/* Back button */}
      <Button variant="ghost" asChild className="-ml-4">
        <Link href="/">
          <ArrowLeft className="mr-2 h-4 w-4" />
          Back to portfolios
        </Link>
      </Button>

      {/* Form card */}
      <Card>
        <CardHeader>
          <CardTitle>Create Portfolio</CardTitle>
          <CardDescription>
            Create a new portfolio to track your investments. You can add
            transactions and sync market data after creation.
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
                      <Input
                        placeholder="e.g., Main Investment Portfolio"
                        {...field}
                      />
                    </FormControl>
                    <FormDescription>
                      Choose a descriptive name for your portfolio
                    </FormDescription>
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
                      All values will be converted to this currency for
                      reporting
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <div className="flex gap-4">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => router.back()}
                >
                  Cancel
                </Button>
                <Button type="submit" disabled={createPortfolio.isPending}>
                  {createPortfolio.isPending && (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  )}
                  Create Portfolio
                </Button>
              </div>
            </form>
          </Form>
        </CardContent>
      </Card>
    </div>
  );
}
