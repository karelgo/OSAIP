import * as React from "react";
import { cn } from "../lib/cn";

/**
 * Shimmering placeholder block; static under prefers-reduced-motion.
 * Size it with className, e.g. <Skeleton className="h-4 w-48" />.
 */
export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div aria-hidden="true" className={cn("ui-skeleton rounded-md", className)} {...props} />;
}
