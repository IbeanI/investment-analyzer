"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

interface PortfolioNavProps {
  portfolioId: number;
}

const navItems = [
  { label: "Overview", href: "" },
  { label: "Holdings", href: "/holdings" },
  { label: "Analytics", href: "/analytics" },
  { label: "Transactions", href: "/transactions" },
  { label: "Settings", href: "/settings" },
];

export function PortfolioNav({ portfolioId }: PortfolioNavProps) {
  const pathname = usePathname();
  const basePath = `/portfolios/${portfolioId}`;

  return (
    <nav className="flex items-center gap-1 border-b mb-6">
      {navItems.map((item) => {
        const href = `${basePath}${item.href}`;
        const isActive =
          item.href === ""
            ? pathname === basePath
            : pathname.startsWith(href);

        return (
          <Link
            key={item.label}
            href={href}
            className={cn(
              "px-4 py-2 text-sm font-medium transition-colors relative",
              "hover:text-foreground",
              isActive
                ? "text-foreground"
                : "text-muted-foreground"
            )}
          >
            {item.label}
            {isActive && (
              <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-primary" />
            )}
          </Link>
        );
      })}
    </nav>
  );
}
