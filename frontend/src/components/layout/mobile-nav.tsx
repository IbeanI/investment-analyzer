"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Home, Briefcase, Plus, BarChart3, Settings } from "lucide-react";
import { cn } from "@/lib/utils";

// -----------------------------------------------------------------------------
// Navigation Items
// -----------------------------------------------------------------------------

const navItems = [
  {
    label: "Home",
    href: "/",
    icon: Home,
  },
  {
    label: "Portfolios",
    href: "/portfolios",
    icon: Briefcase,
  },
  {
    label: "Add",
    href: "/portfolios/new",
    icon: Plus,
    isAction: true,
  },
  {
    label: "Analytics",
    href: "/analytics",
    icon: BarChart3,
  },
  {
    label: "Settings",
    href: "/settings",
    icon: Settings,
  },
];

// -----------------------------------------------------------------------------
// Mobile Navigation Component
// -----------------------------------------------------------------------------

export function MobileNav() {
  const pathname = usePathname();

  return (
    <nav className="lg:hidden fixed bottom-0 left-0 right-0 z-50 bg-background border-t border-border safe-area-pb">
      <ul className="flex items-center justify-around h-16">
        {navItems.map((item) => {
          const isActive =
            pathname === item.href ||
            (item.href !== "/" && pathname.startsWith(item.href));

          return (
            <li key={item.href} className="flex-1">
              <Link
                href={item.href}
                className={cn(
                  "flex flex-col items-center justify-center h-full gap-1 transition-colors",
                  item.isAction
                    ? "text-primary"
                    : isActive
                      ? "text-primary"
                      : "text-muted-foreground"
                )}
              >
                <div
                  className={cn(
                    "flex items-center justify-center",
                    item.isAction &&
                      "h-10 w-10 rounded-full bg-primary text-primary-foreground -mt-4"
                  )}
                >
                  <item.icon
                    className={cn("h-5 w-5", item.isAction && "h-6 w-6")}
                  />
                </div>
                <span className="text-xs">{item.label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
