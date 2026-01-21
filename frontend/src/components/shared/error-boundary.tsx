"use client";

import { Component, ReactNode } from "react";
import { AlertCircle, RefreshCw, Home } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import Link from "next/link";

interface ErrorBoundaryProps {
  children: ReactNode;
  fallback?: ReactNode;
  onError?: (error: Error, errorInfo: React.ErrorInfo) => void;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error("Error caught by boundary:", error, errorInfo);
    this.props.onError?.(error, errorInfo);
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <ErrorFallback
          error={this.state.error}
          onReset={this.handleReset}
        />
      );
    }

    return this.props.children;
  }
}

// Default error fallback component
interface ErrorFallbackProps {
  error: Error | null;
  onReset?: () => void;
}

export function ErrorFallback({ error, onReset }: ErrorFallbackProps) {
  return (
    <div className="flex items-center justify-center min-h-[400px] p-4">
      <Card className="max-w-md w-full">
        <CardHeader className="text-center">
          <div className="mx-auto mb-4 h-12 w-12 rounded-full bg-red-100 dark:bg-red-900/20 flex items-center justify-center">
            <AlertCircle className="h-6 w-6 text-red-600 dark:text-red-400" />
          </div>
          <CardTitle>Something went wrong</CardTitle>
          <CardDescription>
            An unexpected error occurred. Please try again.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {error && (
            <div className="p-3 bg-muted rounded-lg text-sm font-mono text-muted-foreground overflow-auto max-h-32">
              {error.message}
            </div>
          )}
          <div className="flex gap-2">
            {onReset && (
              <Button onClick={onReset} className="flex-1">
                <RefreshCw className="mr-2 h-4 w-4" />
                Try again
              </Button>
            )}
            <Button variant="outline" asChild className="flex-1">
              <Link href="/">
                <Home className="mr-2 h-4 w-4" />
                Go home
              </Link>
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

// Inline error display for smaller sections
interface InlineErrorProps {
  title?: string;
  message: string;
  onRetry?: () => void;
}

export function InlineError({ title = "Error", message, onRetry }: InlineErrorProps) {
  return (
    <Alert variant="destructive">
      <AlertCircle className="h-4 w-4" />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription className="flex items-center justify-between">
        <span>{message}</span>
        {onRetry && (
          <Button variant="outline" size="sm" onClick={onRetry}>
            <RefreshCw className="mr-2 h-3 w-3" />
            Retry
          </Button>
        )}
      </AlertDescription>
    </Alert>
  );
}

// Network error component
interface NetworkErrorProps {
  onRetry?: () => void;
}

export function NetworkError({ onRetry }: NetworkErrorProps) {
  return (
    <div className="flex flex-col items-center justify-center min-h-[300px] p-4 text-center">
      <div className="mb-4 h-16 w-16 rounded-full bg-muted flex items-center justify-center">
        <AlertCircle className="h-8 w-8 text-muted-foreground" />
      </div>
      <h3 className="text-lg font-semibold mb-2">Connection Error</h3>
      <p className="text-muted-foreground mb-4 max-w-sm">
        Unable to connect to the server. Please check your internet connection and try again.
      </p>
      {onRetry && (
        <Button onClick={onRetry}>
          <RefreshCw className="mr-2 h-4 w-4" />
          Try again
        </Button>
      )}
    </div>
  );
}

// Not found error
interface NotFoundErrorProps {
  title?: string;
  message?: string;
  backLink?: string;
  backLabel?: string;
}

export function NotFoundError({
  title = "Not found",
  message = "The resource you're looking for doesn't exist or has been removed.",
  backLink = "/",
  backLabel = "Go back home",
}: NotFoundErrorProps) {
  return (
    <div className="flex flex-col items-center justify-center min-h-[400px] p-4 text-center">
      <div className="mb-4 text-6xl font-bold text-muted-foreground/50">404</div>
      <h3 className="text-lg font-semibold mb-2">{title}</h3>
      <p className="text-muted-foreground mb-6 max-w-sm">{message}</p>
      <Button asChild>
        <Link href={backLink}>
          <Home className="mr-2 h-4 w-4" />
          {backLabel}
        </Link>
      </Button>
    </div>
  );
}

// Permission denied error
export function PermissionDenied() {
  return (
    <div className="flex flex-col items-center justify-center min-h-[400px] p-4 text-center">
      <div className="mb-4 h-16 w-16 rounded-full bg-yellow-100 dark:bg-yellow-900/20 flex items-center justify-center">
        <AlertCircle className="h-8 w-8 text-yellow-600 dark:text-yellow-400" />
      </div>
      <h3 className="text-lg font-semibold mb-2">Access Denied</h3>
      <p className="text-muted-foreground mb-6 max-w-sm">
        You don't have permission to access this resource.
      </p>
      <Button asChild>
        <Link href="/">
          <Home className="mr-2 h-4 w-4" />
          Go back home
        </Link>
      </Button>
    </div>
  );
}

// Query error wrapper for React Query errors
interface QueryErrorProps {
  error: Error;
  onRetry?: () => void;
  compact?: boolean;
}

export function QueryError({ error, onRetry, compact = false }: QueryErrorProps) {
  const isNetworkError =
    error.message.includes("Network") ||
    error.message.includes("fetch") ||
    error.message.includes("Failed to fetch");

  if (isNetworkError) {
    return <NetworkError onRetry={onRetry} />;
  }

  if (compact) {
    return (
      <InlineError
        message={error.message || "An error occurred"}
        onRetry={onRetry}
      />
    );
  }

  return <ErrorFallback error={error} onReset={onRetry} />;
}
