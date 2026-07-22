import * as React from "react";
import { Command as CommandPrimitive } from "cmdk";
import { Search } from "lucide-react";
import { cn } from "../lib/cn";
import { Dialog, DialogContent, DialogTitle, type DialogContentProps } from "./Dialog";
import { Kbd } from "./Kbd";

// cmdk wrapper styled as the ⌘K omnibar surface (§6.3(5)). Keyboard
// navigation (arrows, Enter, typeahead filtering) comes from cmdk itself.

export const Command = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive>
>(({ className, ...props }, ref) => (
  <CommandPrimitive
    ref={ref}
    className={cn(
      "flex h-full w-full flex-col overflow-hidden rounded-lg bg-surface-raised text-fg",
      className,
    )}
    {...props}
  />
));
Command.displayName = "Command";

export interface CommandDialogProps {
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Accessible dialog name, visually hidden. */
  title?: string;
  children: React.ReactNode;
  contentProps?: Omit<DialogContentProps, "children">;
}

/** The ⌘K omnibar: a top-anchored dialog wrapping a Command surface. */
export function CommandDialog({
  open,
  onOpenChange,
  title = "Command palette",
  children,
  contentProps,
}: CommandDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        hideClose
        aria-describedby=""
        {...contentProps}
        className={cn(
          "top-24 max-w-xl translate-y-0 gap-0 overflow-hidden p-0",
          contentProps?.className,
        )}
      >
        <DialogTitle className="sr-only">{title}</DialogTitle>
        <Command>{children}</Command>
      </DialogContent>
    </Dialog>
  );
}

export const CommandInput = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive.Input>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.Input>
>(({ className, ...props }, ref) => (
  <div className="flex items-center gap-2 border-b border-border px-3" cmdk-input-wrapper="">
    <Search aria-hidden="true" className="size-4 shrink-0 text-faint" />
    <CommandPrimitive.Input
      ref={ref}
      className={cn(
        "flex h-11 w-full bg-transparent py-3 text-sm text-fg outline-none placeholder:text-faint disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    />
  </div>
));
CommandInput.displayName = "CommandInput";

export const CommandList = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive.List>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.List>
>(({ className, ...props }, ref) => (
  <CommandPrimitive.List
    ref={ref}
    className={cn("max-h-80 overflow-y-auto overflow-x-hidden", className)}
    {...props}
  />
));
CommandList.displayName = "CommandList";

export const CommandEmpty = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive.Empty>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.Empty>
>(({ className, ...props }, ref) => (
  <CommandPrimitive.Empty
    ref={ref}
    className={cn("py-6 text-center text-sm text-muted", className)}
    {...props}
  />
));
CommandEmpty.displayName = "CommandEmpty";

export const CommandGroup = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive.Group>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.Group>
>(({ className, ...props }, ref) => (
  <CommandPrimitive.Group
    ref={ref}
    className={cn(
      "overflow-hidden p-1 text-fg [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-faint",
      className,
    )}
    {...props}
  />
));
CommandGroup.displayName = "CommandGroup";

export const CommandSeparator = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive.Separator>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.Separator>
>(({ className, ...props }, ref) => (
  <CommandPrimitive.Separator
    ref={ref}
    className={cn("-mx-1 h-px bg-border", className)}
    {...props}
  />
));
CommandSeparator.displayName = "CommandSeparator";

export interface CommandItemProps
  extends React.ComponentPropsWithoutRef<typeof CommandPrimitive.Item> {
  /** Leading icon slot (a lucide icon element). */
  icon?: React.ReactNode;
  /** Trailing hint slot — keyboard shortcut or object kind. */
  hint?: React.ReactNode;
}

export const CommandItem = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive.Item>,
  CommandItemProps
>(({ className, icon, hint, children, ...props }, ref) => (
  <CommandPrimitive.Item
    ref={ref}
    className={cn(
      "relative flex cursor-default select-none items-center gap-2 rounded-sm px-2 py-1.5 text-sm text-fg outline-none data-[selected=true]:bg-bg-subtle data-[disabled=true]:pointer-events-none data-[disabled=true]:opacity-50",
      className,
    )}
    {...props}
  >
    {icon ? (
      <span aria-hidden="true" className="flex size-4 items-center justify-center text-muted [&>svg]:size-4">
        {icon}
      </span>
    ) : null}
    <span className="flex-1 truncate">{children}</span>
    {hint ? <Kbd>{hint}</Kbd> : null}
  </CommandPrimitive.Item>
));
CommandItem.displayName = "CommandItem";
