import * as React from "react";
import { cn } from "../lib/cn";

export interface EmptyStateProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Icon slot — pass a lucide icon element. */
  icon?: React.ReactNode;
  title: string;
  description?: React.ReactNode;
  /** CTA slot — empty states are starting points (§6.3(9)), so offer actions. */
  children?: React.ReactNode;
}

export function EmptyState({
  icon,
  title,
  description,
  children,
  className,
  ...props
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-1.5 rounded-lg border border-dashed border-border px-6 py-12 text-center",
        className,
      )}
      {...props}
    >
      {icon ? (
        <div
          aria-hidden="true"
          className="mb-2 flex size-10 items-center justify-center rounded-full bg-bg-subtle text-muted [&>svg]:size-5"
        >
          {icon}
        </div>
      ) : null}
      <h3 className="text-sm font-semibold text-fg">{title}</h3>
      {description ? <p className="max-w-sm text-sm text-muted">{description}</p> : null}
      {children ? <div className="mt-3 flex flex-wrap items-center justify-center gap-2">{children}</div> : null}
    </div>
  );
}
