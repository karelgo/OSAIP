import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "../lib/cn";
import { Spinner } from "./Spinner";

export const buttonVariants = cva(
  "inline-flex select-none items-center justify-center gap-1.5 whitespace-nowrap rounded-md text-sm font-medium transition-colors duration-fast focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        primary: "bg-accent text-accent-text hover:bg-accent-hover",
        secondary:
          "border border-border bg-surface text-fg hover:border-border-strong hover:bg-bg-subtle",
        ghost: "text-fg hover:bg-bg-subtle",
        danger: "bg-danger-solid text-accent-text hover:bg-danger-solid-hover",
      },
      size: {
        sm: "h-7 rounded-sm px-2.5 text-xs",
        md: "h-control px-3.5",
      },
    },
    defaultVariants: {
      variant: "primary",
      size: "md",
    },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  /** Render the child element instead of a <button> (Radix Slot). */
  asChild?: boolean;
  /** Show a spinner and block interaction while a submit/action runs. */
  loading?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    { className, variant, size, asChild = false, loading = false, disabled, children, ...props },
    ref,
  ) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        ref={ref}
        className={cn(buttonVariants({ variant, size }), className)}
        disabled={disabled || loading}
        aria-busy={loading || undefined}
        {...props}
      >
        {/* Slot requires a single child, so the spinner is only injected for
            plain buttons; asChild callers compose their own loading state. */}
        {loading && !asChild ? <Spinner /> : null}
        {children}
      </Comp>
    );
  },
);
Button.displayName = "Button";
