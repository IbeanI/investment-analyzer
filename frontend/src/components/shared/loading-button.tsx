"use client";

import { forwardRef, ComponentProps } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type ButtonProps = ComponentProps<typeof Button>;

interface LoadingButtonProps extends ButtonProps {
  isLoading?: boolean;
  loadingText?: string;
}

export const LoadingButton = forwardRef<HTMLButtonElement, LoadingButtonProps>(
  ({ isLoading, loadingText, children, disabled, className, ...props }, ref) => {
    return (
      <Button
        ref={ref}
        disabled={disabled || isLoading}
        className={cn(className)}
        {...props}
      >
        {isLoading ? (
          <>
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            {loadingText || children}
          </>
        ) : (
          children
        )}
      </Button>
    );
  }
);

LoadingButton.displayName = "LoadingButton";

// Submit button with built-in loading state from form
interface SubmitButtonProps extends Omit<LoadingButtonProps, "type"> {
  isPending?: boolean;
}

export const SubmitButton = forwardRef<HTMLButtonElement, SubmitButtonProps>(
  ({ isPending, children, ...props }, ref) => {
    return (
      <LoadingButton
        ref={ref}
        type="submit"
        isLoading={isPending}
        loadingText="Saving..."
        {...props}
      >
        {children}
      </LoadingButton>
    );
  }
);

SubmitButton.displayName = "SubmitButton";

// Icon button with loading state
interface IconButtonProps extends ButtonProps {
  isLoading?: boolean;
  icon: React.ReactNode;
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(
  ({ isLoading, icon, disabled, className, ...props }, ref) => {
    return (
      <Button
        ref={ref}
        size="icon"
        disabled={disabled || isLoading}
        className={cn(className)}
        {...props}
      >
        {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : icon}
      </Button>
    );
  }
);

IconButton.displayName = "IconButton";
