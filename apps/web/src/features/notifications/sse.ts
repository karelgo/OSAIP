// The ONE SSE client (§6.6, ADR-0003): a single reconnecting EventSource driving
// TanStack Query invalidation and toasts. This file is the recorded exemption to the
// no-hand-written-fetch rule (ADR-0001) — EventSource cannot be generated.
import type { QueryClient } from "@tanstack/react-query";
import {
  getMeQueryKey,
  listNotificationsQueryKey,
  listProjectsQueryKey,
} from "@osaip/api-client";
import { toast } from "@osaip/ui";

export interface BusEvent {
  type: string;
  topic: string;
  project_id: string | null;
  payload: Record<string, unknown>;
  ts: string;
}

// Topic → generated query keys to invalidate (never string literals).
function invalidateForTopic(queryClient: QueryClient, topic: string) {
  switch (topic) {
    case "notifications":
      void queryClient.invalidateQueries({ queryKey: listNotificationsQueryKey() });
      break;
    case "projects":
      void queryClient.invalidateQueries({ queryKey: listProjectsQueryKey() });
      break;
    case "control":
      void queryClient.invalidateQueries(); // reset: cursor predates retention
      break;
    default:
      break;
  }
}

const SEVERITIES = new Set(["info", "success", "warning", "error"]);

export function startEventStream(queryClient: QueryClient): () => void {
  let source: EventSource | null = null;
  let disposed = false;

  function connect() {
    if (disposed) return;
    source = new EventSource("/api/v1/events");

    source.addEventListener("notifications", (event) => {
      const data = JSON.parse((event as MessageEvent).data) as BusEvent;
      invalidateForTopic(queryClient, "notifications");
      if (data.type === "notification.created") {
        const payload = data.payload as {
          title?: string;
          body?: string;
          severity?: string;
        };
        const severity = SEVERITIES.has(payload.severity ?? "")
          ? (payload.severity as "info" | "success" | "warning" | "error")
          : "info";
        toast({
          title: payload.title ?? "Notification",
          description: payload.body,
          severity,
        });
      }
    });
    source.addEventListener("projects", () => invalidateForTopic(queryClient, "projects"));
    source.addEventListener("control", () => invalidateForTopic(queryClient, "control"));
    source.addEventListener("jobs", () => {
      /* run drawer arrives in Phase 2 */
    });

    source.onerror = () => {
      // EventSource reconnects on its own with Last-Event-ID; if the session died,
      // /me refetch will bounce the user to login.
      void queryClient.invalidateQueries({ queryKey: getMeQueryKey() });
    };
  }

  connect();
  return () => {
    disposed = true;
    source?.close();
  };
}
