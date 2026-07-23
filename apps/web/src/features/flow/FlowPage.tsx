// Flow (/p/$key): the project's living graph (§6.3(1), §6.4). A brand-new project sees
// the onboarding checklist (moved here from ProjectHome, keeping the project-home +
// onboarding-checklist testids); once anything is built, the same route shows the
// canvas + inspector. Selection, inspector tab, and the run drawer are all in the URL
// (?sel/?tab/?job) so every view is deep-linkable and reload-stable (§6.2, §6.7).
import { Badge, Button, EmptyState, Skeleton, toast } from "@osaip/ui";
import {
  createBuild,
  getFlowOptions,
  getFlowQueryKey,
  getProjectOptions,
  listJobsQueryKey,
  type FlowOut,
} from "@osaip/api-client";
import { GraphCanvas, layout } from "@osaip/canvas";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { AlertTriangle, ArrowRight, Bot, Cable, Database, Hammer, Play, Upload } from "lucide-react";
import { useMemo } from "react";
import { problemToast } from "../../lib/problem";
import { Inspector, type InspectorTab } from "./Inspector";
import { RunDrawer } from "./RunDrawer";
import { useColorMode } from "./useColorMode";
import { isEmptyGraph, parseSelection, toGraph } from "./vm";

const ROUTE_ID = "/_authed/_shell/p/$key/";

const SOURCE_STATUSES = new Set(["source", "source_empty"]);

export function FlowPage() {
  const { key } = useParams({ from: ROUTE_ID });
  const search = useSearch({ from: ROUTE_ID });
  const navigate = useNavigate();
  const colorMode = useColorMode();
  const project = useQuery(getProjectOptions({ path: { key } }));
  const flow = useQuery(getFlowOptions({ path: { key } }));

  const graph = useMemo(() => {
    if (!flow.data) return { nodes: [], edges: [] };
    const built = toGraph(flow.data);
    return { nodes: layout(built.nodes, built.edges), edges: built.edges };
  }, [flow.data]);

  if (flow.isLoading || project.isLoading) {
    return (
      <div className="p-6" data-testid="project-home">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="mt-4 h-[60vh] w-full" />
      </div>
    );
  }

  if (flow.isError || !flow.data) {
    return (
      <div className="flex h-full items-center justify-center p-8" data-testid="project-home">
        <EmptyState
          icon={<AlertTriangle aria-hidden className="size-8" />}
          title="Couldn't load this project's flow"
          description="It may not exist, or you may not be a member. Ask a project admin to add you."
        >
          <Button variant="secondary" onClick={() => flow.refetch()}>
            Retry
          </Button>
        </EmptyState>
      </div>
    );
  }

  const data = flow.data;
  const canEdit = data.capabilities.can_edit;

  if (isEmptyGraph(data)) {
    return <OnboardingHome projectKey={key} projectName={project.data?.name} canEdit={canEdit} />;
  }

  const selection = parseSelection(search.sel);
  const tab: InspectorTab = search.tab ?? "configure";

  function selectNode(nodeId: string | null) {
    void navigate({
      to: "/p/$key",
      params: { key },
      search: {
        sel: nodeId ?? undefined,
        tab: nodeId ? search.tab : undefined,
        job: search.job,
      },
      replace: true,
    });
  }
  function setTab(next: InspectorTab) {
    void navigate({
      to: "/p/$key",
      params: { key },
      search: { sel: search.sel, tab: next === "configure" ? undefined : next, job: search.job },
      replace: true,
    });
  }
  function openJob(jobId: string) {
    void navigate({
      to: "/p/$key",
      params: { key },
      search: { sel: search.sel, tab: search.tab, job: jobId },
    });
  }
  function closeJob() {
    void navigate({
      to: "/p/$key",
      params: { key },
      search: { sel: search.sel, tab: search.tab, job: undefined },
    });
  }

  return (
    <div className="flex h-full flex-col" data-testid="project-home">
      <FlowHeader
        projectKey={key}
        projectName={project.data?.name ?? key}
        flow={data}
        selection={selection}
        canEdit={canEdit}
        onQueued={openJob}
      />
      <div className="flex min-h-0 flex-1">
        <div className="min-w-0 flex-1">
          <GraphCanvas
            data-testid="flow-canvas"
            nodes={graph.nodes}
            edges={graph.edges}
            selectedId={search.sel ?? null}
            onSelect={selectNode}
            colorMode={colorMode}
          />
        </div>
        {selection && (
          <Inspector
            projectKey={key}
            flow={data}
            selection={selection}
            tab={tab}
            onTab={setTab}
            onSelectNode={selectNode}
            onOpenJob={openJob}
            canEdit={canEdit}
            colorMode={colorMode}
          />
        )}
      </div>
      {search.job && (
        <RunDrawer projectKey={key} jobId={search.job} canEdit={canEdit} onClose={closeJob} />
      )}
    </div>
  );
}

// ── Header + Build ─────────────────────────────────────────────────────────────────

function producedNames(flow: FlowOut): string[] {
  return flow.datasets
    .filter((dataset) => !SOURCE_STATUSES.has(dataset.status))
    .map((dataset) => dataset.name);
}

function FlowHeader({
  projectKey,
  projectName,
  flow,
  selection,
  canEdit,
  onQueued,
}: {
  projectKey: string;
  projectName: string;
  flow: FlowOut;
  selection: ReturnType<typeof parseSelection>;
  canEdit: boolean;
  onQueued: (jobId: string) => void;
}) {
  const queryClient = useQueryClient();

  // Selection-specific targets: a produced dataset builds itself; a recipe builds its
  // outputs. Otherwise fall back to building everything downstream of sources.
  const selectionTargets = useMemo(() => {
    if (!selection) return [];
    if (selection.kind === "dataset") {
      return producedNames(flow).includes(selection.name) ? [selection.name] : [];
    }
    return flow.recipes.find((recipe) => recipe.id === selection.id)?.output_datasets ?? [];
  }, [selection, flow]);

  const allTargets = useMemo(() => producedNames(flow), [flow]);
  const targets = selectionTargets.length > 0 ? selectionTargets : allTargets;
  const label = selectionTargets.length > 0 ? "Build" : "Build all";

  const build = useMutation({
    mutationFn: (buildTargets: string[]) =>
      createBuild({ path: { key: projectKey }, body: { targets: buildTargets }, throwOnError: true }),
    onSuccess: async (response) => {
      await queryClient.invalidateQueries({ queryKey: getFlowQueryKey({ path: { key: projectKey } }) });
      await queryClient.invalidateQueries({ queryKey: listJobsQueryKey({ path: { key: projectKey } }) });
      toast({
        title: "Build queued",
        description: `${targets.length} target${targets.length === 1 ? "" : "s"} — opening the run.`,
        severity: "info",
      });
      onQueued(response.data.id);
    },
    onError: (error: unknown) => problemToast(error, "Couldn't start the build"),
  });

  return (
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-6 py-3">
      <div className="flex items-center gap-2">
        <h1 className="text-lg font-semibold tracking-tight">{projectName}</h1>
        <Badge variant="neutral">Flow</Badge>
      </div>
      {canEdit && (
        <Button
          data-testid="build-button"
          loading={build.isPending}
          disabled={targets.length === 0}
          onClick={() => build.mutate(targets)}
        >
          <Hammer aria-hidden className="size-4" /> {label}
        </Button>
      )}
    </header>
  );
}

// ── Onboarding (empty graph) ─────────────────────────────────────────────────────

interface ChecklistStep {
  icon: typeof Cable;
  title: string;
  description: string;
  path: string;
  search?: Record<string, string>;
  phase?: number;
}

const CHECKLIST: ChecklistStep[] = [
  {
    icon: Cable,
    title: "Connect a data source",
    description: "Postgres, S3, or file upload",
    path: "settings",
    search: { tab: "connections" },
  },
  {
    icon: Database,
    title: "Register a dataset",
    description: "Schema, preview, and profiling",
    path: "datasets",
  },
  {
    icon: Play,
    title: "Build your first Flow",
    description: "Visual recipes over your data",
    path: ".",
  },
  {
    icon: Bot,
    title: "Create an agent",
    description: "Grounded in your data and knowledge",
    path: "agents",
    phase: 6,
  },
];

function OnboardingHome({
  projectKey,
  projectName,
  canEdit,
}: {
  projectKey: string;
  projectName: string | undefined;
  canEdit: boolean;
}) {
  return (
    <div className="mx-auto max-w-5xl p-6" data-testid="project-home">
      <div className="flex items-center gap-3">
        <h1 className="text-xl font-semibold tracking-tight">{projectName}</h1>
        <Badge variant="neutral">Flow</Badge>
      </div>
      <p className="mt-1 text-sm text-muted">
        Your datasets and recipes will render here as a living graph — status pulses travel along the
        edges while builds run. Get your first data in to begin.
      </p>

      {canEdit && (
        <div className="mt-6 flex flex-wrap gap-2" data-testid="flow-starting-points">
          <Button asChild>
            <Link to="/p/$key/datasets" params={{ key: projectKey }} search={{ panel: "upload" }}>
              <Upload aria-hidden className="size-4" /> Upload a CSV
            </Link>
          </Button>
          <Button variant="secondary" asChild>
            <Link to="/p/$key/datasets" params={{ key: projectKey }}>
              <ArrowRight aria-hidden className="size-4" /> Create a recipe from a dataset
            </Link>
          </Button>
        </div>
      )}

      <section className="mt-8">
        <h2 className="text-sm font-medium text-muted">Get started</h2>
        <ol className="mt-3 grid gap-3 sm:grid-cols-2" data-testid="onboarding-checklist">
          {CHECKLIST.map((step, index) => (
            <li key={step.title}>
              <Link
                to={step.path === "." ? "/p/$key" : `/p/$key/${step.path}`}
                params={{ key: projectKey }}
                search={step.search}
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
                    {step.description}
                    {step.phase ? ` · phase ${step.phase}` : ""}
                  </span>
                </span>
              </Link>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
