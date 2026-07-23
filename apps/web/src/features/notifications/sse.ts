// The ONE SSE client (§6.6, ADR-0003): a single reconnecting EventSource driving
// TanStack Query invalidation and toasts. This file is the recorded exemption to the
// no-hand-written-fetch rule (ADR-0001) — EventSource cannot be generated.
import type { QueryClient } from "@tanstack/react-query";
import {
  getDatasetQueryKey,
  getFlowQueryKey,
  getJobQueryKey,
  getMeQueryKey,
  listDatasetsQueryKey,
  listJobsQueryKey,
  listNotificationsQueryKey,
  listProjectsQueryKey,
  listRecipesQueryKey,
} from "@osaip/api-client";
import { toast } from "@osaip/ui";

export interface BusEvent {
  type: string;
  topic: string;
  project_id: string | null;
  payload: Record<string, unknown>;
  ts: string;
}

// Project-scoped queries embed the key in their generated keys, and the SSE handler
// only knows the topic — so we match on the stable `_id` segment, derived from the
// generated key helpers themselves (never string literals). `_id` is shared across a
// query's plain and infinite variants, so one id set covers both.
const DATASET_QUERY_IDS = new Set<string>(
  [
    listDatasetsQueryKey({ path: { key: "" } }),
    getDatasetQueryKey({ path: { key: "", name: "" } }),
  ].map(([entry]) => entry._id),
);
const FLOW_QUERY_IDS = new Set<string>(
  [getFlowQueryKey({ path: { key: "" } })].map(([entry]) => entry._id),
);
const JOB_QUERY_IDS = new Set<string>(
  [
    listJobsQueryKey({ path: { key: "" } }),
    getJobQueryKey({ path: { key: "", job_id: "" } }),
  ].map(([entry]) => entry._id),
);
const RECIPE_QUERY_IDS = new Set<string>(
  [listRecipesQueryKey({ path: { key: "" } })].map(([entry]) => entry._id),
);

function invalidateByIds(queryClient: QueryClient, ids: Set<string>) {
  void queryClient.invalidateQueries({
    predicate: (query) => {
      const first = query.queryKey[0];
      return (
        typeof first === "object" &&
        first !== null &&
        ids.has((first as { _id?: string })._id ?? "")
      );
    },
  });
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
    case "datasets":
      // A dataset change (schema, classification, new version) also shifts Flow status.
      invalidateByIds(queryClient, DATASET_QUERY_IDS);
      invalidateByIds(queryClient, FLOW_QUERY_IDS);
      break;
    case "jobs":
      // A build step advancing changes both the run views and the Flow node statuses.
      invalidateByIds(queryClient, JOB_QUERY_IDS);
      invalidateByIds(queryClient, FLOW_QUERY_IDS);
      break;
    case "flow":
      // Recipe/graph edits (create, patch, archive) reshape the Flow and the recipe list.
      invalidateByIds(queryClient, FLOW_QUERY_IDS);
      invalidateByIds(queryClient, RECIPE_QUERY_IDS);
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
    source.addEventListener("datasets", () => invalidateForTopic(queryClient, "datasets"));
    source.addEventListener("jobs", () => invalidateForTopic(queryClient, "jobs"));
    source.addEventListener("flow", () => invalidateForTopic(queryClient, "flow"));
    source.addEventListener("control", () => invalidateForTopic(queryClient, "control"));

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
