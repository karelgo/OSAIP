import * as React from "react";
import { cn } from "../lib/cn";

export type InputProps = React.InputHTMLAttributes<HTMLInputElement>;

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type = "text", ...props }, ref) => (
    <input
      ref={ref}
      type={type}
      className={cn(
        "flex h-control w-full rounded-md border border-border bg-surface px-3 text-sm text-fg transition-colors duration-fast placeholder:text-faint focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg disabled:cursor-not-allowed disabled:opacity-50 aria-[invalid=true]:border-status-danger",
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = "Input";

export type InputLabelProps = React.LabelHTMLAttributes<HTMLLabelElement>;

export const InputLabel = React.forwardRef<HTMLLabelElement, InputLabelProps>(
  ({ className, ...props }, ref) => (
    <label
      ref={ref}
      className={cn(
        "text-sm font-medium leading-none text-fg peer-disabled:cursor-not-allowed peer-disabled:opacity-70",
        className,
      )}
      {...props}
    />
  ),
);
InputLabel.displayName = "InputLabel";

export interface FieldProps {
  label: React.ReactNode;
  /** Error message; sets aria-invalid and wires aria-describedby on the control. */
  error?: React.ReactNode;
  /** Help text shown when there is no error. */
  hint?: React.ReactNode;
  /** Control id; generated when omitted. */
  id?: string;
  className?: string;
  /** Exactly one form control (Input, Select trigger, textarea, …). */
  children: React.ReactElement;
}

/** Label + control + error slot with the aria wiring done for you. */
export function Field({ label, error, hint, id, className, children }: FieldProps) {
  const autoId = React.useId();
  const fieldId = id ?? autoId;
  const errorId = `${fieldId}-error`;
  const hintId = `${fieldId}-hint`;
  const describedBy =
    [error ? errorId : null, hint && !error ? hintId : null].filter(Boolean).join(" ") ||
    undefined;

  const control = React.cloneElement(children as React.ReactElement<Record<string, unknown>>, {
    id: fieldId,
    "aria-describedby": describedBy,
    "aria-invalid": error ? true : undefined,
  });

  return (
    <div className={cn("flex w-full flex-col gap-1.5", className)}>
      <InputLabel htmlFor={fieldId}>{label}</InputLabel>
      {control}
      {hint && !error ? (
        <p id={hintId} className="text-xs text-muted">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} className="text-xs text-status-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}
