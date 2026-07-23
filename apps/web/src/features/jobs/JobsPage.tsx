// Jobs (/p/$key/jobs): a cursor-paginated run history with status filter chips. Each
// row deep-links to the run detail. Status filter lives in ?status (§6.7).
import { Button, EmptyState, Skeleton, Table, TBody, TD, TH, THead, TR, cn } from "@osaip/ui";
import { listJobsInfiniteOptions, type JobListOut } from "@osaip/api-client";
import { useInfiniteQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { AlertTriangle, Monitor } from "lucide-react";
import type { InfiniteData } from "@tanstack/react-query";
import { StatusDot, isActiveJob } from "../flow/RunDrawer";

const ROUTE_ID = "/_authed/_shell/p/$key/jobs";

const FILTERS = ["all", "running", "queued", "succeeded", "failed"] as const;
export type JobStatusFilter = (typeof FILTERS)[number];

function formatDuration(start: string | null, end: string | null): string {
  if (!start) return "—";
  const seconds = Math.max(0, Math.round(((end ? new Date(end).getTime() : Date.now()) - new Date(start).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

export function JobsPage() {
  const { key } = useParams({ from: ROUTE_ID });
  const search = useSearch({ from: ROUTE_ID });
  const navigate = useNavigate();
  const status = search.status ?? "all";

  const jobs = useInfiniteQuery({
    ...listJobsInfiniteOptions({
      path: { key },
      query: status === "all" ? {} : { status },
    }),
    // First page: no cursor. Carrying `path` keeps this in the object branch of the
    // generated queryFn (a string param is treated as the cursor).
    initialPageParam: { path: { key } },
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    refetchInterval: (query) => {
      const pages = (query.state.data as InfiniteData<JobListOut> | undefined)?.pages;
      const active = pages?.some((page) => page.items.some((job) => isActiveJob(job.status)));
      return active ? 2000 : false;
    },
  });

  const items = jobs.data?.pages.flatMap((page) => page.items) ?? [];

  function setStatus(next: JobStatusFilter) {
    void navigate({
      to: "/p/$key/jobs",
      params: { key },
      search: next === "all" ? {} : { status: next },
    });
  }

  return (
    <div className="mx-auto max-w-5xl p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Jobs</h1>
          <p className="text-sm text-muted">Every build run, newest first.</p>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-1.5" role="group" aria-label="Filter by status">
        {FILTERS.map((filter) => (
          <button
            key={filter}
            type="button"
            data-testid={`jobs-filter-${filter}`}
            aria-pressed={status === filter}
            onClick={() => setStatus(filter)}
            className={cn(
              "rounded-full border px-3 py-1 text-xs capitalize focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
              status === filter
                ? "border-accent bg-accent-subtle text-fg"
                : "border-border text-muted hover:bg-bg-subtle",
            )}
          >
            {filter}
          </button>
        ))}
      </div>

      <div className="mt-6">
        {jobs.isLoading && (
          <div className="space-y-2" data-testid="jobs-loading">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
        )}

        {jobs.isError && (
          <EmptyState
            icon={<AlertTriangle aria-hidden className="size-8" />}
            title="Couldn't load jobs"
            description="The API did not respond. Check your connection, then retry."
          >
            <Button variant="secondary" onClick={() => jobs.refetch()}>
              Retry
            </Button>
          </EmptyState>
        )}

        {jobs.isSuccess && items.length === 0 && (
          <EmptyState
            icon={<Monitor aria-hidden className="size-8" />}
            title="No runs yet"
            description="Build a dataset from the Flow to queue your first run."
          >
            <Button variant="secondary" asChild>
              <Link to="/p/$key" params={{ key }}>
                Go to Flow
              </Link>
            </Button>
          </EmptyState>
        )}

        {jobs.isSuccess && items.length > 0 && (
          <Table data-testid="jobs-table">
            <THead>
              <TR>
                <TH>Status</TH>
                <TH>Trigger</TH>
                <TH numeric>Steps</TH>
                <TH numeric>Duration</TH>
                <TH>Created</TH>
              </TR>
            </THead>
            <TBody>
              {items.map((job) => (
                <TR
                  key={job.id}
                  data-testid="jobs-row"
                  className="cursor-pointer"
                  onClick={() =>
                    void navigate({ to: "/p/$key/jobs/$jobId", params: { key, jobId: job.id } })
                  }
                >
                  <TD>
                    <span className="inline-flex items-center gap-2">
                      <StatusDot status={job.status} />
                      <Link
                        to="/p/$key/jobs/$jobId"
                        params={{ key, jobId: job.id }}
                        className="font-medium capitalize text-fg underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                        onClick={(event) => event.stopPropagation()}
                      >
                        {job.status}
                      </Link>
                    </span>
                  </TD>
                  <TD className="text-muted">{job.trigger}</TD>
                  <TD numeric className="tabular-nums">
                    {job.steps.length}
                  </TD>
                  <TD numeric className="tabular-nums text-muted">
                    {formatDuration(job.started_at, job.finished_at)}
                  </TD>
                  <TD className="whitespace-nowrap text-muted">
                    {new Date(job.created_at).toLocaleString()}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}

        {jobs.hasNextPage && (
          <div className="mt-4 flex justify-center">
            <Button
              variant="secondary"
              data-testid="jobs-load-more"
              loading={jobs.isFetchingNextPage}
              onClick={() => void jobs.fetchNextPage()}
            >
              Load more
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
