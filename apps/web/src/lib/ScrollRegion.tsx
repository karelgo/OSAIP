// Focusable scroll container for data grids that overflow (axe wcag2a
// scrollable-region-focusable: keyboard users must be able to scroll it). The
// @osaip/ui Table wrapper is not focusable, so grids that cap their height render
// a plain <table> inside this region instead.
import * as React from "react";
import { cn } from "@osaip/ui";

export interface ScrollRegionProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Accessible name for the region (required for role="region"). */
  label: string;
}

export const ScrollRegion = React.forwardRef<HTMLDivElement, ScrollRegionProps>(
  ({ label, className, children, ...props }, ref) => (
    <div
      ref={ref}
      role="region"
      aria-label={label}
      tabIndex={0}
      className={cn(
        "relative w-full overflow-auto focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
        className,
      )}
      {...props}
    >
      {children}
    </div>
  ),
);
ScrollRegion.displayName = "ScrollRegion";

/** Table element with the @osaip/ui Table typography, minus its scroll wrapper. */
export function PlainTable({
  className,
  ...props
}: React.TableHTMLAttributes<HTMLTableElement>) {
  return (
    <table className={cn("w-full caption-bottom border-collapse text-sm", className)} {...props} />
  );
}

/** Class for a sticky header row inside a ScrollRegion. */
export const STICKY_THEAD = "[&_th]:sticky [&_th]:top-0 [&_th]:z-10 [&_th]:bg-surface";
