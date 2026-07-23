// Run drawer (§6.3(4), canonical): a bottom drawer over the Flow showing a job's step
// timeline and a live log tail. The timeline + log components are exported so the Jobs
// detail page renders the same thing inline. Build-action toasts deep-link here (?job=).
import { Button, EmptyState, Skeleton, cn, toast } from "@osaip/ui";
import {
  cancelJob,
  getJobOptions,
  getJobQueryKey,
  getStepLog,
  type JobOut,
  type StepOut,
} from "@osaip/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { ScrollRegion } from "../../lib/ScrollRegion";
import { asProblem, problemToast } from "../../lib/problem";

export function isActiveJob(status: string): boolean {
  return status === "running" || status === "queued";
}

function isActiveStep(status: string): boolean {
  return status === "running" || status === "queued" || status === "pending";
}

const STEP_TONE: Record<string, string> = {
  succeeded: "bg-status-success",
  failed: "bg-status-danger",
  running: "bg-status-info",
  queued: "bg-faint",
  pending: "bg-faint",
  skipped: "bg-faint",
};

export function StatusDot({ status }: { status: string }) {
  return (
    <span
      role="img"
      aria-label={status}
      title={status}
      className={cn(
        "inline-block size-2.5 shrink-0 rounded-full",
        STEP_TONE[status] ?? "bg-faint",
        status === "running" && "motion-safe:animate-pulse",
      )}
    />
  );
}

function formatDuration(start: string | null, end: string | null): string {
  if (!start) return "—";
  const from = new Date(start).getTime();
  const to = end ? new Date(end).getTime() : Date.now();
  const seconds = Math.max(0, Math.round((to - from) / 1000));
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

// ── Step timeline ────────────────────────────────────────────────────────────────

export function StepTimeline({
  steps,
  selectedOrdinal,
  onSelect,
}: {
  steps: StepOut[];
  selectedOrdinal: number | null;
  onSelect: (ordinal: number) => void;
}) {
  if (steps.length === 0) {
    return <p className="text-sm text-muted">This job has no steps.</p>;
  }
  return (
    <ol className="space-y-1" data-testid="run-drawer-steps">
      {steps.map((step) => (
        <li key={step.ordinal}>
          <button
            type="button"
            data-testid="run-drawer-step"
            aria-current={step.ordinal === selectedOrdinal}
            onClick={() => onSelect(step.ordinal)}
            className={cn(
              "flex w-full items-center gap-3 rounded-md border px-3 py-2 text-left text-sm",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
              step.ordinal === selectedOrdinal
                ? "border-accent bg-accent-subtle"
                : "border-border hover:bg-bg-subtle",
            )}
          >
            <StatusDot status={step.status} />
            <span className="min-w-0 flex-1 truncate">
              <span className="font-mono text-xs text-muted">{step.recipe_name ?? "—"}</span>
              <span className="mx-1.5 text-faint" aria-hidden>
                →
              </span>
              <span className="font-medium">{step.target_dataset_name ?? "—"}</span>
            </span>
            <span className="shrink-0 tabular-nums text-xs text-faint">
              {formatDuration(step.started_at, step.finished_at)}
            </span>
          </button>
          {step.error ? (
            <p className="ml-6 mt-1 text-xs text-status-danger">{step.error}</p>
          ) : null}
        </li>
      ))}
    </ol>
  );
}

// ── Live log tail ────────────────────────────────────────────────────────────────

export function LogTail({
  projectKey,
  jobId,
  ordinal,
  running,
}: {
  projectKey: string;
  jobId: string;
  ordinal: number;
  running: boolean;
}) {
  // Reset happens by remount: callers key this component on job+ordinal, so content
  // starts empty for each step (no synchronous setState inside the effect).
  const [content, setContent] = useState("");
  const preRef = useRef<HTMLPreElement>(null);

  useEffect(() => {
    let cancelled = false;
    let offset = 0;

    const tick = async () => {
      try {
        const response = await getStepLog({
          path: { key: projectKey, job_id: jobId, ordinal },
          query: { after: offset },
          throwOnError: true,
        });
        if (cancelled) return;
        if (response.data.content) setContent((prev) => prev + response.data.content);
        offset = response.data.next_offset;
      } catch {
        // transient — the interval retries; a fatal error surfaces via the job query.
      }
    };

    void tick();
    const interval = running ? setInterval(() => void tick(), 1000) : null;
    return () => {
      cancelled = true;
      if (interval) clearInterval(interval);
    };
  }, [projectKey, jobId, ordinal, running]);

  useEffect(() => {
    const pre = preRef.current;
    if (pre) pre.scrollTop = pre.scrollHeight;
  }, [content]);

  return (
    <ScrollRegion
      label="Step log"
      data-testid="run-drawer-log"
      className="max-h-56 rounded-md border border-border bg-bg-subtle"
    >
      <pre ref={preRef} className="max-h-56 overflow-auto p-3 font-mono text-xs leading-relaxed text-fg">
        {content || (running ? "Waiting for output…" : "No output.")}
      </pre>
    </ScrollRegion>
  );
}

// ── Shared run content (drawer body + Jobs detail) ─────────────────────────────────

export function RunContent({
  projectKey,
  jobId,
  canEdit,
}: {
  projectKey: string;
  jobId: string;
  canEdit: boolean;
}) {
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<number | null>(null);

  const job = useQuery({
    ...getJobOptions({ path: { key: projectKey, job_id: jobId } }),
    refetchInterval: (query) => {
      const data = query.state.data as JobOut | undefined;
      return data && isActiveJob(data.status) ? 1000 : false;
    },
  });

  const steps = useMemo(() => job.data?.steps ?? [], [job.data]);

  // Default the log to the running step, else the last step.
  const effectiveOrdinal = useMemo(() => {
    if (selected !== null && steps.some((step) => step.ordinal === selected)) return selected;
    const active = steps.find((step) => isActiveStep(step.status));
    return active?.ordinal ?? steps[steps.length - 1]?.ordinal ?? null;
  }, [selected, steps]);

  const cancel = useMutation({
    mutationFn: () => cancelJob({ path: { key: projectKey, job_id: jobId }, throwOnError: true }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: getJobQueryKey({ path: { key: projectKey, job_id: jobId } }),
      });
      toast({ title: "Cancelling run", severity: "info" });
    },
    onError: (error: unknown) => problemToast(error, "Couldn't cancel the run"),
  });

  if (job.isLoading) {
    return (
      <div className="space-y-2" data-testid="run-loading">
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }
  if (job.isError || !job.data) {
    return (
      <EmptyState
        icon={<AlertTriangle aria-hidden className="size-8" />}
        title="Couldn't load this run"
        description={asProblem(job.error).hint ?? asProblem(job.error).detail ?? "The run may have expired."}
      >
        <Button variant="secondary" onClick={() => job.refetch()}>
          Retry
        </Button>
      </EmptyState>
    );
  }

  const data = job.data;
  const activeStep = steps.find((step) => step.ordinal === effectiveOrdinal);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-muted">
          <span className="font-medium capitalize text-fg">{data.status}</span> · {data.kind} ·{" "}
          {data.trigger}
          {data.attempts > 1 ? ` · attempt ${data.attempts}` : ""}
        </p>
        {canEdit && isActiveJob(data.status) && (
          <Button
            variant="danger"
            size="sm"
            data-testid="run-cancel"
            loading={cancel.isPending}
            onClick={() => cancel.mutate()}
          >
            Cancel run
          </Button>
        )}
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <StepTimeline steps={steps} selectedOrdinal={effectiveOrdinal} onSelect={setSelected} />
        {effectiveOrdinal !== null && activeStep ? (
          <LogTail
            key={`${jobId}:${effectiveOrdinal}`}
            projectKey={projectKey}
            jobId={jobId}
            ordinal={effectiveOrdinal}
            running={isActiveStep(activeStep.status)}
          />
        ) : (
          <p className="text-sm text-muted">Select a step to see its log.</p>
        )}
      </div>
    </div>
  );
}

// ── Drawer shell ───────────────────────────────────────────────────────────────────

export function RunDrawer({
  projectKey,
  jobId,
  canEdit,
  onClose,
}: {
  projectKey: string;
  jobId: string;
  canEdit: boolean;
  onClose: () => void;
}) {
  return (
    <aside
      data-testid="run-drawer"
      aria-label="Run details"
      className="pointer-events-auto fixed inset-x-0 bottom-0 z-40 max-h-[60vh] overflow-auto border-t border-border bg-surface p-4 shadow-3"
    >
      <div className="mx-auto max-w-5xl">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold">
            Run <span className="font-mono text-xs text-muted">{jobId.slice(0, 8)}</span>
          </h2>
          <Button variant="ghost" size="sm" aria-label="Close run details" onClick={onClose}>
            <X aria-hidden className="size-4" />
          </Button>
        </div>
        <div className="mt-3">
          <RunContent projectKey={projectKey} jobId={jobId} canEdit={canEdit} />
        </div>
      </div>
    </aside>
  );
}
