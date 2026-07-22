// Project home (/p/$key): Flow canvas placeholder + onboarding checklist (§6.3(9):
// new projects get connect → dataset → build → agent starting points).
import { Badge, Button, EmptyState, Skeleton } from "@osaip/ui";
import { getProjectOptions } from "@osaip/api-client";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import {
  AlertTriangle,
  ArrowRight,
  Bot,
  Cable,
  Database,
  GitBranch,
  Play,
} from "lucide-react";

const CHECKLIST = [
  {
    icon: Cable,
    title: "Connect a data source",
    description: "Postgres, S3, or file upload",
    path: "datasets",
    phase: 1,
  },
  {
    icon: Database,
    title: "Register a dataset",
    description: "Schema, preview, and profiling",
    path: "datasets",
    phase: 1,
  },
  {
    icon: Play,
    title: "Build your first Flow",
    description: "Visual recipes over your data",
    path: ".",
    phase: 2,
  },
  {
    icon: Bot,
    title: "Create an agent",
    description: "Grounded in your data and knowledge",
    path: "agents",
    phase: 6,
  },
];

export function ProjectHome() {
  const { key } = useParams({ from: "/_authed/_shell/p/$key" });
  const project = useQuery(getProjectOptions({ path: { key } }));

  if (project.isLoading) {
    return (
      <div className="p-6" data-testid="project-loading">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="mt-4 h-40 w-full" />
      </div>
    );
  }

  if (project.isError) {
    return (
      <div className="flex h-full items-center justify-center p-8">
        <EmptyState
          icon={<AlertTriangle aria-hidden className="size-8" />}
          title="Couldn't load this project"
          description="It may not exist, or you may not be a member. Ask a project admin to add you."
        >
          <Button variant="secondary" onClick={() => project.refetch()}>
            Retry
          </Button>
        </EmptyState>
      </div>
    );
  }

  const data = project.data;

  return (
    <div className="mx-auto max-w-5xl p-6" data-testid="project-home">
      <div className="flex items-center gap-3">
        <h1 className="text-xl font-semibold tracking-tight">{data?.name}</h1>
        <Badge variant={data?.status === "active" ? "success" : "neutral"}>{data?.status}</Badge>
        <Badge variant="neutral">{data?.role}</Badge>
      </div>
      {data?.description && <p className="mt-1 text-sm text-muted">{data.description}</p>}

      <section className="mt-8">
        <h2 className="text-sm font-medium text-muted">Get started</h2>
        <ol className="mt-3 grid gap-3 sm:grid-cols-2" data-testid="onboarding-checklist">
          {CHECKLIST.map((step, index) => (
            <li key={step.title}>
              <Link
                to={step.path === "." ? "/p/$key" : `/p/$key/${step.path}`}
                params={{ key }}
                className="flex items-start gap-3 rounded-lg border border-border bg-surface p-4 hover:border-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              >
                <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-accent-subtle">
                  <step.icon aria-hidden className="size-4" />
                </span>
                <span className="min-w-0">
                  <span className="flex items-center gap-2 text-sm font-medium">
                    {index + 1}. {step.title}
                    <ArrowRight aria-hidden className="size-3.5 text-faint" />
                  </span>
                  <span className="block text-xs text-muted">
                    {step.description} · phase {step.phase}
                  </span>
                </span>
              </Link>
            </li>
          ))}
        </ol>
      </section>

      <section className="mt-8">
        <h2 className="text-sm font-medium text-muted">Flow</h2>
        <div className="mt-3 rounded-lg border border-dashed border-border p-10">
          <EmptyState
            icon={<GitBranch aria-hidden className="size-8" />}
            title="The Flow canvas arrives in phase 2"
            description="Your datasets and recipes will render here as a living graph — status pulses travel along the edges while builds run."
          />
        </div>
      </section>
    </div>
  );
}
