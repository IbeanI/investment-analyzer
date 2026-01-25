"use client";

import { Sidebar, MobileNav, Header } from "@/components/layout";
import { useAuth } from "@/providers";
import { Skeleton } from "@/components/ui/skeleton";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { isLoading, isAuthenticated } = useAuth();

  // Show loading state while checking auth
  if (isLoading) {
    return (
      <div className="flex h-screen">
        {/* Sidebar skeleton (desktop) */}
        <div className="hidden lg:flex flex-col w-60 border-r border-border p-4 space-y-4">
          <Skeleton className="h-8 w-32" />
          <div className="space-y-2">
            {[1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        </div>

        {/* Main content skeleton */}
        <div className="flex-1 flex flex-col">
          <div className="h-16 border-b border-border px-4 flex items-center justify-between">
            <Skeleton className="h-6 w-32" />
            <Skeleton className="h-9 w-9 rounded-full" />
          </div>
          <div className="flex-1 p-6 space-y-6">
            <Skeleton className="h-8 w-48" />
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {[1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-32 rounded-lg" />
              ))}
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Don't render if not authenticated (will redirect)
  if (!isAuthenticated) {
    return null;
  }

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      {/* Skip link for keyboard navigation (WCAG 2.4.1) */}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:top-4 focus:left-4 focus:px-4 focus:py-2 focus:bg-primary focus:text-primary-foreground focus:rounded-md focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
      >
        Skip to main content
      </a>

      {/* Sidebar (desktop only) */}
      <Sidebar />

      {/* Main content area */}
      <div className="flex-1 flex flex-col overflow-hidden min-h-0">
        {/* Header */}
        <Header />

        {/* Page content */}
        <main
          id="main-content"
          className="flex-1 min-h-0 overflow-y-auto pb-20 lg:pb-0 scrollbar-thin"
          role="main"
          aria-label="Main content"
        >
          <div className="container mx-auto p-4 lg:p-6">{children}</div>
        </main>

        {/* Mobile bottom navigation */}
        <MobileNav />
      </div>
    </div>
  );
}
