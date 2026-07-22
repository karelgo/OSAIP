import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "../lib/cn";

export const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-xs font-medium",
  {
    variants: {
      variant: {
        neutral: "bg-bg-subtle text-muted",
        accent: "bg-accent-subtle text-accent-strong",
        info: "bg-status-info-subtle text-status-info",
        success: "bg-status-success-subtle text-status-success",
        warning: "bg-status-warning-subtle text-status-warning",
        danger: "bg-status-danger-subtle text-status-danger",
      },
    },
    defaultVariants: {
      variant: "neutral",
    },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
