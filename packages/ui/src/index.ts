// @osaip/ui — OSAIP design system v1 (PROJECT_SPEC §6.4).
// Consumers also import "@osaip/ui/styles.css" and extend their Tailwind
// config with "@osaip/ui/tailwind-preset".

export { cn } from "./lib/cn";

export { Button, buttonVariants, type ButtonProps } from "./components/Button";
export {
  Input,
  InputLabel,
  Field,
  type InputProps,
  type InputLabelProps,
  type FieldProps,
} from "./components/Input";
export {
  Select,
  SelectGroup,
  SelectValue,
  SelectTrigger,
  SelectContent,
  SelectLabel,
  SelectItem,
  SelectSeparator,
} from "./components/Select";
export { Checkbox, type CheckboxProps } from "./components/Checkbox";
export { Badge, badgeVariants, type BadgeProps } from "./components/Badge";
export { Tabs, TabsList, TabsTrigger, TabsContent } from "./components/Tabs";
export {
  Dialog,
  DialogTrigger,
  DialogClose,
  DialogPortal,
  DialogOverlay,
  DialogContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
  DialogDescription,
  ConfirmDialog,
  type DialogContentProps,
  type ConfirmDialogProps,
} from "./components/Dialog";
export {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuGroup,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  type DropdownMenuItemProps,
} from "./components/DropdownMenu";
export { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from "./components/Tooltip";
export { Toaster, type ToasterProps } from "./components/Toast";
export {
  toast,
  dismissToast,
  clearToasts,
  type ToastOptions,
  type ToastItem,
  type ToastSeverity,
  type ToastActionOptions,
} from "./lib/toast-store";
export {
  Table,
  THead,
  TBody,
  TR,
  TH,
  TD,
  type TableProps,
  type THProps,
  type TDProps,
} from "./components/Table";
export { Skeleton } from "./components/Skeleton";
export { EmptyState, type EmptyStateProps } from "./components/EmptyState";
export {
  Command,
  CommandDialog,
  CommandInput,
  CommandList,
  CommandEmpty,
  CommandGroup,
  CommandItem,
  CommandSeparator,
  type CommandDialogProps,
  type CommandItemProps,
} from "./components/Command";
export { Kbd } from "./components/Kbd";
export { Spinner, type SpinnerProps } from "./components/Spinner";
