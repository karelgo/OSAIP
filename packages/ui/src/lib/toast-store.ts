// Tiny listener-based toast store (no state library). The imperative `toast()`
// API pushes items; <Toaster /> subscribes via useSyncExternalStore.

export type ToastSeverity = "info" | "success" | "warning" | "error";

export interface ToastActionOptions {
  label: string;
  onClick: () => void;
}

export interface ToastOptions {
  title: string;
  description?: string;
  severity?: ToastSeverity;
  action?: ToastActionOptions;
  /** Milliseconds before auto-dismiss; defaults to the Toaster's duration. */
  duration?: number;
}

export interface ToastItem extends ToastOptions {
  id: string;
  severity: ToastSeverity;
}

let nextId = 0;
let items: readonly ToastItem[] = [];
const listeners = new Set<() => void>();

function emit(): void {
  for (const listener of listeners) listener();
}

/** Show a toast. Returns its id for programmatic dismissal. */
export function toast(options: ToastOptions): string {
  const id = `toast-${++nextId}`;
  items = [...items, { severity: "info", ...options, id }];
  emit();
  return id;
}

/** Dismiss a toast by id (no-op when already gone). */
export function dismissToast(id: string): void {
  const next = items.filter((item) => item.id !== id);
  if (next.length !== items.length) {
    items = next;
    emit();
  }
}

/** Remove all toasts (used by tests and route changes). */
export function clearToasts(): void {
  if (items.length > 0) {
    items = [];
    emit();
  }
}

export function subscribeToasts(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getToasts(): readonly ToastItem[] {
  return items;
}
