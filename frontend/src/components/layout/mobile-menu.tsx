"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import {
  Home,
  Briefcase,
  Settings,
  LogOut,
  Moon,
  Sun,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useAuth } from "@/providers";

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
    label: "Settings",
    href: "/settings",
    icon: Settings,
  },
];

// -----------------------------------------------------------------------------
// Mobile Menu Component
// -----------------------------------------------------------------------------

export function MobileMenu() {
  const pathname = usePathname();
  const { logout, user } = useAuth();
  const { theme, setTheme } = useTheme();

  const toggleTheme = () => setTheme(theme === "dark" ? "light" : "dark");

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <SheetHeader className="px-6 py-4 border-b border-border">
        <SheetTitle className="flex items-center gap-2">
          <Briefcase className="h-6 w-6 text-primary" />
          <span>Portfolio Analyzer</span>
        </SheetTitle>
      </SheetHeader>

      {/* Navigation */}
      <nav className="flex-1 py-4">
        <ul className="space-y-1 px-2">
          {navItems.map((item) => {
            const isActive =
              pathname === item.href ||
              (item.href !== "/" && pathname.startsWith(item.href));

            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className={cn(
                    "flex items-center gap-3 px-4 py-3 rounded-md transition-colors",
                    isActive
                      ? "bg-accent text-accent-foreground"
                      : "text-foreground hover:bg-accent hover:text-accent-foreground"
                  )}
                >
                  <item.icon className="h-5 w-5 shrink-0" />
                  <span className="text-base">{item.label}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      {/* Bottom Section */}
      <div className="border-t border-border p-4 space-y-2">
        {/* Theme Toggle */}
        <Button
          variant="ghost"
          onClick={toggleTheme}
          className="w-full justify-start gap-3 px-4 py-3 h-auto"
        >
          {theme === "dark" ? (
            <Sun className="h-5 w-5" />
          ) : (
            <Moon className="h-5 w-5" />
          )}
          <span className="text-base">
            {theme === "dark" ? "Light mode" : "Dark mode"}
          </span>
        </Button>

        {/* User Info */}
        {user && (
          <>
            <Separator />
            <div className="px-4 py-2 text-sm text-muted-foreground truncate">
              {user.email}
            </div>
            <Button
              variant="ghost"
              onClick={logout}
              className="w-full justify-start gap-3 px-4 py-3 h-auto text-destructive hover:text-destructive"
            >
              <LogOut className="h-5 w-5" />
              <span className="text-base">Logout</span>
            </Button>
          </>
        )}
      </div>
    </div>
  );
}
