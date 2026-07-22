// Notifications inbox (§6.6): right-side drawer listing inbox items with read state.
import {
  Badge,
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  EmptyState,
  Skeleton,
  cn,
} from "@osaip/ui";
import {
  listNotificationsOptions,
  listNotificationsQueryKey,
  markAllRead,
  markRead,
} from "@osaip/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellOff, Inbox } from "lucide-react";
import { useShell } from "../shell/theme";

const SEVERITY_VARIANT: Record<string, "info" | "success" | "warning" | "danger"> = {
  info: "info",
  success: "success",
  warning: "warning",
  error: "danger",
};

export function InboxDrawer() {
  const { inboxOpen, setInboxOpen } = useShell();
  const queryClient = useQueryClient();
  const inbox = useQuery({ ...listNotificationsOptions(), enabled: inboxOpen });

  const readOne = useMutation({
    mutationFn: (id: string) => markRead({ path: { notification_id: id }, throwOnError: true }),
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: listNotificationsQueryKey() }),
  });
  const readAll = useMutation({
    mutationFn: () => markAllRead({ throwOnError: true }),
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: listNotificationsQueryKey() }),
  });

  const items = inbox.data?.items ?? [];

  return (
    <Dialog open={inboxOpen} onOpenChange={setInboxOpen}>
      <DialogContent
        data-testid="inbox-drawer"
        className="fixed inset-y-0 right-0 left-auto h-full w-full max-w-md translate-x-0 translate-y-0 rounded-none border-l border-border sm:rounded-none"
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Inbox aria-hidden className="size-4" /> Inbox
            {(inbox.data?.unread_count ?? 0) > 0 && (
              <Badge variant="accent">{inbox.data?.unread_count} unread</Badge>
            )}
          </DialogTitle>
          <DialogDescription>
            Approvals, run failures, and platform notices land here.
          </DialogDescription>
        </DialogHeader>
        <div className="flex items-center justify-end">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => readAll.mutate()}
            disabled={readAll.isPending || (inbox.data?.unread_count ?? 0) === 0}
          >
            Mark all as read
          </Button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          {inbox.isLoading && (
            <div className="space-y-2 p-1">
              <Skeleton className="h-14 w-full" />
              <Skeleton className="h-14 w-full" />
              <Skeleton className="h-14 w-full" />
            </div>
          )}
          {!inbox.isLoading && items.length === 0 && (
            <EmptyState
              icon={<BellOff aria-hidden className="size-8" />}
              title="No notifications"
              description="Job results, approvals, and platform notices will show up here."
            />
          )}
          <ul className="space-y-1">
            {items.map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  data-testid="inbox-item"
                  onClick={() => item.read_at === null && readOne.mutate(item.id)}
                  className={cn(
                    "w-full rounded-md border border-border p-3 text-left",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                    item.read_at === null ? "bg-surface" : "opacity-60",
                  )}
                >
                  <div className="flex items-center gap-2">
                    <Badge variant={SEVERITY_VARIANT[item.severity] ?? "neutral"}>
                      {item.severity}
                    </Badge>
                    <span className="truncate text-sm font-medium">{item.title}</span>
                    {item.read_at === null && (
                      <span aria-label="unread" className="ml-auto size-2 rounded-full bg-accent" />
                    )}
                  </div>
                  {item.body && <p className="mt-1 text-sm text-muted">{item.body}</p>}
                  <time className="mt-1 block text-xs text-faint">
                    {new Date(item.created_at).toLocaleString()}
                  </time>
                </button>
              </li>
            ))}
          </ul>
        </div>
      </DialogContent>
    </Dialog>
  );
}
