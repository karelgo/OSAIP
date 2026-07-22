import * as React from "react";
import * as ToastPrimitive from "@radix-ui/react-toast";
import { X } from "lucide-react";
import { cn } from "../lib/cn";
import {
  dismissToast,
  getToasts,
  subscribeToasts,
  type ToastItem,
  type ToastSeverity,
} from "../lib/toast-store";
import { Button } from "./Button";

const severityBorder: Record<ToastSeverity, string> = {
  info: "border-l-status-info",
  success: "border-l-status-success",
  warning: "border-l-status-warning",
  error: "border-l-status-danger",
};

function ToastCard({ item }: { item: ToastItem }) {
  return (
    <ToastPrimitive.Root
      duration={item.duration}
      onOpenChange={(open) => {
        if (!open) dismissToast(item.id);
      }}
      className={cn(
        "group pointer-events-auto relative flex w-full items-start gap-3 overflow-hidden rounded-md border border-border border-l-4 bg-surface-raised p-4 pr-8 shadow-2 transition-all data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:slide-in-from-bottom-2 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[swipe=end]:translate-x-[var(--radix-toast-swipe-end-x)] data-[swipe=move]:translate-x-[var(--radix-toast-swipe-move-x)] data-[swipe=move]:transition-none",
        severityBorder[item.severity],
      )}
    >
      <div className="grid flex-1 gap-1">
        <ToastPrimitive.Title className="text-sm font-medium text-fg">
          {item.title}
        </ToastPrimitive.Title>
        {item.description ? (
          <ToastPrimitive.Description className="text-sm text-muted">
            {item.description}
          </ToastPrimitive.Description>
        ) : null}
      </div>
      {item.action ? (
        <ToastPrimitive.Action altText={item.action.label} asChild>
          <Button variant="secondary" size="sm" onClick={item.action.onClick}>
            {item.action.label}
          </Button>
        </ToastPrimitive.Action>
      ) : null}
      <ToastPrimitive.Close
        aria-label="Dismiss"
        className="absolute right-2 top-2 rounded-sm p-1 text-faint transition-colors duration-fast hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg"
      >
        <X aria-hidden="true" className="size-4" />
      </ToastPrimitive.Close>
    </ToastPrimitive.Root>
  );
}

export interface ToasterProps {
  /** Default auto-dismiss in ms; individual toasts can override. */
  duration?: number;
}

/** Toast outlet — mount once near the app root, bottom-right viewport. */
export function Toaster({ duration = 5000 }: ToasterProps) {
  const items = React.useSyncExternalStore(subscribeToasts, getToasts, getToasts);
  return (
    <ToastPrimitive.Provider swipeDirection="right" duration={duration}>
      {items.map((item) => (
        <ToastCard key={item.id} item={item} />
      ))}
      <ToastPrimitive.Viewport className="fixed bottom-4 right-4 z-[100] flex w-full max-w-sm flex-col gap-2 outline-none" />
    </ToastPrimitive.Provider>
  );
}
