import * as React from "react";
import { cn } from "../lib/cn";

// Plain semantic table. Density-aware: cell padding follows --cell-py, which
// tightens under [data-density="compact"]. Numeric cells get tabular numerals.

const StickyHeaderContext = React.createContext(false);

export interface TableProps extends React.TableHTMLAttributes<HTMLTableElement> {
  /** Keep the header row visible while the container scrolls. */
  stickyHeader?: boolean;
  /** Class for the scroll container wrapping the table. */
  containerClassName?: string;
}

export const Table = React.forwardRef<HTMLTableElement, TableProps>(
  ({ className, containerClassName, stickyHeader = false, ...props }, ref) => (
    <StickyHeaderContext.Provider value={stickyHeader}>
      <div className={cn("relative w-full overflow-auto", containerClassName)}>
        <table
          ref={ref}
          className={cn("w-full caption-bottom border-collapse text-sm", className)}
          {...props}
        />
      </div>
    </StickyHeaderContext.Provider>
  ),
);
Table.displayName = "Table";

export const THead = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => {
  const sticky = React.useContext(StickyHeaderContext);
  return (
    <thead
      ref={ref}
      className={cn(
        "[&_tr]:border-b [&_tr]:border-border",
        // Sticky is applied to the header cells (reliable across browsers).
        sticky && "[&_th]:sticky [&_th]:top-0 [&_th]:z-10 [&_th]:bg-surface",
        className,
      )}
      {...props}
    />
  );
});
THead.displayName = "THead";

export const TBody = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <tbody ref={ref} className={cn("[&_tr:last-child]:border-0", className)} {...props} />
));
TBody.displayName = "TBody";

export const TR = React.forwardRef<HTMLTableRowElement, React.HTMLAttributes<HTMLTableRowElement>>(
  ({ className, ...props }, ref) => (
    <tr
      ref={ref}
      className={cn(
        "border-b border-border transition-colors duration-fast hover:bg-bg-subtle data-[state=selected]:bg-accent-subtle",
        className,
      )}
      {...props}
    />
  ),
);
TR.displayName = "TR";

export interface THProps extends React.ThHTMLAttributes<HTMLTableCellElement> {
  /** Right-align and use tabular numerals for number columns. */
  numeric?: boolean;
}

export const TH = React.forwardRef<HTMLTableCellElement, THProps>(
  ({ className, numeric = false, ...props }, ref) => (
    <th
      ref={ref}
      className={cn(
        "px-3 py-cell-y text-left align-middle text-xs font-medium text-muted",
        numeric && "tabular text-right",
        className,
      )}
      {...props}
    />
  ),
);
TH.displayName = "TH";

export interface TDProps extends React.TdHTMLAttributes<HTMLTableCellElement> {
  /** Right-align and use tabular numerals for number cells. */
  numeric?: boolean;
}

export const TD = React.forwardRef<HTMLTableCellElement, TDProps>(
  ({ className, numeric = false, ...props }, ref) => (
    <td
      ref={ref}
      className={cn(
        "px-3 py-cell-y align-middle text-fg",
        numeric && "tabular text-right font-mono text-[13px]",
        className,
      )}
      {...props}
    />
  ),
);
TD.displayName = "TD";
