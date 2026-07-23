// Styled native <select>, visually matched to @osaip/ui Input. Used where plain
// form semantics matter: react-hook-form register(), Playwright selectOption(),
// and dense inline cells — Radix Select stays the choice for standalone pickers.
import * as React from "react";
import { cn } from "@osaip/ui";

export type NativeSelectProps = React.SelectHTMLAttributes<HTMLSelectElement>;

export const NativeSelect = React.forwardRef<HTMLSelectElement, NativeSelectProps>(
  ({ className, children, ...props }, ref) => (
    <select
      ref={ref}
      className={cn(
        "flex h-control w-full rounded-md border border-border bg-surface px-2.5 text-sm text-fg transition-colors duration-fast focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg disabled:cursor-not-allowed disabled:opacity-50 aria-[invalid=true]:border-status-danger",
        className,
      )}
      {...props}
    >
      {children}
    </select>
  ),
);
NativeSelect.displayName = "NativeSelect";
