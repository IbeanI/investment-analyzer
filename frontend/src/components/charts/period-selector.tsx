"use client";

import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

export type Period = "1M" | "3M" | "6M" | "YTD" | "1Y" | "ALL";

interface PeriodSelectorProps {
  value: Period;
  onChange: (period: Period) => void;
  className?: string;
}

const periods: { value: Period; label: string }[] = [
  { value: "1M", label: "1M" },
  { value: "3M", label: "3M" },
  { value: "6M", label: "6M" },
  { value: "YTD", label: "YTD" },
  { value: "1Y", label: "1Y" },
  { value: "ALL", label: "All" },
];

export function PeriodSelector({
  value,
  onChange,
  className,
}: PeriodSelectorProps) {
  return (
    <Tabs
      value={value}
      onValueChange={(v) => onChange(v as Period)}
      className={className}
    >
      <TabsList className="grid w-full grid-cols-6">
        {periods.map((period) => (
          <TabsTrigger
            key={period.value}
            value={period.value}
            className="text-xs sm:text-sm"
          >
            {period.label}
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  );
}

// Compact version for mobile
export function PeriodSelectorCompact({
  value,
  onChange,
  className,
}: PeriodSelectorProps) {
  return (
    <div className={cn("flex gap-1 flex-wrap", className)}>
      {periods.map((period) => (
        <button
          key={period.value}
          onClick={() => onChange(period.value)}
          className={cn(
            "px-2.5 py-1 text-xs font-medium rounded-md transition-colors",
            value === period.value
              ? "bg-primary text-primary-foreground"
              : "bg-muted hover:bg-muted/80 text-muted-foreground"
          )}
        >
          {period.label}
        </button>
      ))}
    </div>
  );
}
