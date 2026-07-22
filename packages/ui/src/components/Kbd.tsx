import * as React from "react";
import { cn } from "../lib/cn";

/** Small keyboard-hint chip, e.g. <Kbd>⌘K</Kbd>. */
export function Kbd({ className, ...props }: React.HTMLAttributes<HTMLElement>) {
  return (
    <kbd
      className={cn(
        "pointer-events-none inline-flex h-5 min-w-5 select-none items-center justify-center gap-0.5 rounded-sm border border-border bg-bg-subtle px-1 font-mono text-[11px] font-medium text-muted",
        className,
      )}
      {...props}
    />
  );
}
