import type { Metadata } from "next";
import { Briefcase } from "lucide-react";

export const metadata: Metadata = {
  title: "Authentication",
};

export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen flex flex-col lg:flex-row">
      {/* Left panel - branding (hidden on mobile) */}
      <div className="hidden lg:flex lg:w-1/2 bg-primary p-12 flex-col justify-between">
        <div className="flex items-center gap-3 text-primary-foreground">
          <Briefcase className="h-8 w-8" />
          <span className="text-2xl font-bold">Portfolio Analyzer</span>
        </div>
        <div className="space-y-4 text-primary-foreground">
          <h1 className="text-4xl font-bold">
            Track and analyze your investments
          </h1>
          <p className="text-lg opacity-90">
            Professional-grade portfolio analytics for retail investors. Track
            performance, measure risk, and make informed decisions.
          </p>
        </div>
        <p className="text-sm text-primary-foreground/70">
          Institution-grade analysis, made accessible.
        </p>
      </div>

      {/* Right panel - auth form */}
      <div className="flex-1 flex items-center justify-center p-6 lg:p-12">
        <div className="w-full max-w-md">
          {/* Mobile logo */}
          <div className="flex lg:hidden items-center justify-center gap-3 mb-8">
            <Briefcase className="h-8 w-8 text-primary" />
            <span className="text-2xl font-bold">Portfolio Analyzer</span>
          </div>
          {children}
        </div>
      </div>
    </div>
  );
}
