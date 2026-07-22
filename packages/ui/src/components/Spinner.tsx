import { Loader2 } from "lucide-react";
import { cn } from "../lib/cn";

export interface SpinnerProps {
  className?: string;
  /** Accessible label; when set the spinner announces itself as status. */
  label?: string;
}

/** Indeterminate progress indicator. Freezes under prefers-reduced-motion. */
export function Spinner({ className, label }: SpinnerProps) {
  const icon = (
    <Loader2 aria-hidden="true" className={cn("size-4 animate-spin text-current", className)} />
  );
  if (!label) return icon;
  return (
    <span role="status" className="inline-flex items-center">
      {icon}
      <span className="sr-only">{label}</span>
    </span>
  );
}
