// The canonical inspector (§6.3): Configure · Preview · Runs · Lineage · Docs — the
// tab order every later module reuses. Opens when `?sel` is set; reads `?tab` for the
// active tab. Recipe nodes edit their config (with a live draft Preview); dataset nodes
// show a read-only summary plus classification/CP config. Viewers are read-only.
import {
  Badge,
  Button,
  EmptyState,
  Field,
  Input,
  Skeleton,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  toast,
} from "@osaip/ui";
import {
  getDatasetOptions,
  getDatasetQueryKey,
  getFlowQueryKey,
  getRecipeOptions,
  getRecipeQueryKey,
  listDatasetsQueryKey,
  listJobsOptions,
  listRecipesQueryKey,
  patchDataset,
  patchRecipe,
  previewRecipeMutation,
  sampleDatasetOptions,
  type DatasetOut,
  type FlowOut,
  type RecipeOut,
  type StepOut,
} from "@osaip/api-client";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowUpRight, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { NativeSelect } from "../../lib/NativeSelect";
import { asProblem, problemToast } from "../../lib/problem";
import {
  BBN_LEVELS,
  CLASSIFICATIONS,
  CONFIDENTIALITY_LEVELS,
  ClassificationBadges,
  parsePurposeCodes,
} from "../datasets/lib";
import { PreviewGrid } from "./PreviewGrid";
import { RecipeConfigForm } from "./RecipeConfigForm";
import { StatusDot } from "./RunDrawer";
import {
  datasetNodeId,
  neighbors,
  nodeLabel,
  recipeNodeId,
  type Selection,
} from "./vm";

export const INSPECTOR_TABS = ["configure", "preview", "runs", "lineage", "docs"] as const;
export type InspectorTab = (typeof INSPECTOR_TABS)[number];

type Config = Record<string, unknown>;

const TEXTAREA_CLASS =
  "flex w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-fg transition-colors duration-fast placeholder:text-faint focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg disabled:cursor-not-allowed disabled:opacity-50";

export interface InspectorProps {
  projectKey: string;
  flow: FlowOut;
  selection: Exclude<Selection, null>;
  tab: InspectorTab;
  onTab: (tab: InspectorTab) => void;
  onSelectNode: (nodeId: string | null) => void;
  onOpenJob: (jobId: string) => void;
  canEdit: boolean;
  colorMode: "light" | "dark";
}

export function Inspector(props: InspectorProps) {
  if (props.selection.kind === "recipe") {
    return <RecipeInspector {...props} recipeId={props.selection.id} />;
  }
  return <DatasetInspector {...props} datasetName={props.selection.name} />;
}

// ── Shell ──────────────────────────────────────────────────────────────────────────

function InspectorShell({
  title,
  kindLabel,
  badges,
  tab,
  onTab,
  onClose,
  children,
}: {
  title: string;
  kindLabel: string;
  badges?: React.ReactNode;
  tab: InspectorTab;
  onTab: (tab: InspectorTab) => void;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <aside
      data-testid="inspector"
      aria-label="Inspector"
      className="flex h-full w-[26rem] max-w-full shrink-0 flex-col border-l border-border bg-surface"
    >
      <div className="flex items-start justify-between gap-2 border-b border-border p-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="truncate text-sm font-semibold">{title}</h2>
            <Badge variant="neutral">{kindLabel}</Badge>
          </div>
          {badges ? <div className="mt-1.5">{badges}</div> : null}
        </div>
        <Button variant="ghost" size="sm" aria-label="Close inspector" onClick={onClose}>
          <X aria-hidden className="size-4" />
        </Button>
      </div>
      <Tabs
        value={tab}
        onValueChange={(value) => onTab(value as InspectorTab)}
        className="flex min-h-0 flex-1 flex-col"
      >
        <TabsList className="mx-4 mt-3 flex-wrap">
          <TabsTrigger value="configure" data-testid="inspector-tab-configure">
            Configure
          </TabsTrigger>
          <TabsTrigger value="preview" data-testid="inspector-tab-preview">
            Preview
          </TabsTrigger>
          <TabsTrigger value="runs" data-testid="inspector-tab-runs">
            Runs
          </TabsTrigger>
          <TabsTrigger value="lineage" data-testid="inspector-tab-lineage">
            Lineage
          </TabsTrigger>
          <TabsTrigger value="docs" data-testid="inspector-tab-docs">
            Docs
          </TabsTrigger>
        </TabsList>
        <div className="min-h-0 flex-1 overflow-auto p-4">{children}</div>
      </Tabs>
    </aside>
  );
}

function LoadingBody() {
  return (
    <div className="space-y-2" data-testid="inspector-loading">
      <Skeleton className="h-8 w-full" />
      <Skeleton className="h-32 w-full" />
    </div>
  );
}

// ── Recipe inspector ─────────────────────────────────────────────────────────────

function RecipeInspector({
  projectKey,
  flow,
  recipeId,
  tab,
  onTab,
  onSelectNode,
  onOpenJob,
  canEdit,
  colorMode,
}: InspectorProps & { recipeId: string }) {
  const queryClient = useQueryClient();
  const recipe = useQuery(getRecipeOptions({ path: { key: projectKey, recipe_id: recipeId } }));
  const [draft, setDraft] = useState<Config | null>(null);

  // A fresh selection (or a just-saved config) resets the working draft to the stored
  // config. Adjust state during render rather than in an effect (React-recommended).
  const draftKey = `${recipeId}:${recipe.data?.config_hash ?? ""}`;
  const [seenDraftKey, setSeenDraftKey] = useState(draftKey);
  if (seenDraftKey !== draftKey) {
    setSeenDraftKey(draftKey);
    setDraft(null);
  }

  const save = useMutation({
    mutationFn: (config: Config) =>
      patchRecipe({
        path: { key: projectKey, recipe_id: recipeId },
        body: { config },
        throwOnError: true,
      }),
    onSuccess: async () => {
      setDraft(null);
      await queryClient.invalidateQueries({
        queryKey: getRecipeQueryKey({ path: { key: projectKey, recipe_id: recipeId } }),
      });
      await queryClient.invalidateQueries({ queryKey: listRecipesQueryKey({ path: { key: projectKey } }) });
      await queryClient.invalidateQueries({ queryKey: getFlowQueryKey({ path: { key: projectKey } }) });
      toast({ title: "Changes saved", severity: "success" });
    },
    onError: (error: unknown) => problemToast(error, "Couldn't save the recipe"),
  });

  const nodeId = recipeNodeId(recipeId);
  const title = recipe.data?.name ?? nodeLabel(flow, nodeId);

  const effectiveConfig = draft ?? recipe.data?.config ?? {};

  return (
    <InspectorShell
      title={title}
      kindLabel={recipe.data?.kind ?? "recipe"}
      tab={tab}
      onTab={onTab}
      onClose={() => onSelectNode(null)}
    >
      <TabsContent value="configure">
        {recipe.isLoading ? (
          <LoadingBody />
        ) : recipe.isError || !recipe.data ? (
          <InspectorError onRetry={() => recipe.refetch()} error={recipe.error} />
        ) : (
          <RecipeConfigForm
            key={recipe.data.config_hash}
            recipe={recipe.data}
            initialConfig={draft ?? recipe.data.config}
            onChange={setDraft}
            onSave={(config) => save.mutate(config)}
            saving={save.isPending}
            canEdit={canEdit}
            colorMode={colorMode}
          />
        )}
      </TabsContent>

      <TabsContent value="preview">
        {recipe.data ? (
          <RecipePreviewTab
            projectKey={projectKey}
            recipe={recipe.data}
            config={effectiveConfig}
            canEdit={canEdit}
          />
        ) : (
          <LoadingBody />
        )}
      </TabsContent>

      <TabsContent value="runs">
        <RunsTab
          projectKey={projectKey}
          match={(step) => step.recipe_name === recipe.data?.name}
          onOpenJob={onOpenJob}
        />
      </TabsContent>

      <TabsContent value="lineage">
        <LineageTab flow={flow} nodeId={nodeId} onSelectNode={onSelectNode} />
      </TabsContent>

      <TabsContent value="docs">
        {recipe.data ? (
          <RecipeDocs projectKey={projectKey} recipe={recipe.data} canEdit={canEdit} />
        ) : (
          <LoadingBody />
        )}
      </TabsContent>
    </InspectorShell>
  );
}

function RecipePreviewTab({
  projectKey,
  recipe,
  config,
  canEdit,
}: {
  projectKey: string;
  recipe: RecipeOut;
  config: Config;
  canEdit: boolean;
}) {
  const preview = useMutation(previewRecipeMutation());
  const configKey = useMemo(() => JSON.stringify(config), [config]);

  // Debounced draft preview (§6.3(3)) — runs the CURRENT (possibly-unsaved) config.
  useEffect(() => {
    if (!canEdit || recipe.kind === "python") return;
    const timer = setTimeout(() => {
      preview.mutate({
        path: { key: projectKey, recipe_id: recipe.id },
        body: { config, limit: 50 },
      });
    }, 400);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [configKey, canEdit, recipe.kind, recipe.id, projectKey]);

  if (recipe.kind === "python") {
    return (
      <EmptyState
        title="No live preview"
        description="Python recipes run in the sandbox and have no live preview in v1. Build the recipe to run it."
      />
    );
  }
  if (!canEdit) {
    return (
      <EmptyState title="Preview is editor-only" description="Ask a project editor to preview this recipe." />
    );
  }
  if (preview.isPending) {
    return (
      <div className="space-y-2" data-testid="recipe-preview-loading">
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }
  if (preview.isError) {
    return (
      <EmptyState
        icon={<AlertTriangle aria-hidden className="size-8" />}
        title="Couldn't preview this recipe"
        description={
          asProblem(preview.error).hint ??
          asProblem(preview.error).detail ??
          "The engine rejected the current config."
        }
      >
        <Button
          variant="secondary"
          onClick={() =>
            preview.mutate({ path: { key: projectKey, recipe_id: recipe.id }, body: { config, limit: 50 } })
          }
        >
          Retry
        </Button>
      </EmptyState>
    );
  }
  if (!preview.data) {
    return <p className="text-sm text-muted">Preview runs automatically as you edit.</p>;
  }
  if (preview.data.rows.length === 0) {
    return <EmptyState title="No rows" description="The recipe produced an empty preview." />;
  }
  return (
    <PreviewGrid
      data-testid="recipe-preview"
      label={`Preview of ${recipe.name}`}
      columns={preview.data.columns}
      rows={preview.data.rows}
    />
  );
}

function RecipeDocs({
  projectKey,
  recipe,
  canEdit,
}: {
  projectKey: string;
  recipe: RecipeOut;
  canEdit: boolean;
}) {
  const queryClient = useQueryClient();
  const form = useForm<{ name: string; purpose_codes: string }>({
    defaultValues: { name: recipe.name, purpose_codes: recipe.purpose_codes.join(", ") },
  });
  const save = useMutation({
    mutationFn: (values: { name: string; purpose_codes: string }) =>
      patchRecipe({
        path: { key: projectKey, recipe_id: recipe.id },
        body: { name: values.name, purpose_codes: parsePurposeCodes(values.purpose_codes) },
        throwOnError: true,
      }),
    onSuccess: async (_response, values) => {
      await queryClient.invalidateQueries({
        queryKey: getRecipeQueryKey({ path: { key: projectKey, recipe_id: recipe.id } }),
      });
      await queryClient.invalidateQueries({ queryKey: listRecipesQueryKey({ path: { key: projectKey } }) });
      await queryClient.invalidateQueries({ queryKey: getFlowQueryKey({ path: { key: projectKey } }) });
      form.reset(values);
      toast({ title: "Changes saved", severity: "success" });
    },
    onError: (error: unknown) => problemToast(error, "Couldn't save changes"),
  });

  return (
    <form className="space-y-4" onSubmit={form.handleSubmit((values) => save.mutate(values))}>
      <Field label="Name">
        <Input disabled={!canEdit} className="font-mono" {...form.register("name")} />
      </Field>
      <Field label="Purpose codes" hint="Comma-separated (CP-2)">
        <Input disabled={!canEdit} {...form.register("purpose_codes")} />
      </Field>
      {canEdit && (
        <Button type="submit" data-testid="recipe-docs-save" loading={save.isPending} disabled={!form.formState.isDirty}>
          Save changes
        </Button>
      )}
    </form>
  );
}

// ── Dataset inspector ────────────────────────────────────────────────────────────

const datasetConfigSchema = z.object({
  classification: z.enum(["none", "persoonsgegevens", "bijzonder", "bsn"]),
  bbn_level: z.enum(["", "bbn1", "bbn2", "bbn3"]),
  confidentiality: z.enum(["", "intern", "vertrouwelijk", "geheim"]),
  legal_basis: z.string().min(1, "State the legal basis (CP-2)").max(500),
  purpose_codes: z.string().refine((raw) => parsePurposeCodes(raw).length > 0, {
    message: "Give at least one purpose code (CP-2)",
  }),
});
type DatasetConfigValues = z.infer<typeof datasetConfigSchema>;

function DatasetInspector({
  projectKey,
  flow,
  datasetName,
  tab,
  onTab,
  onSelectNode,
  onOpenJob,
  canEdit,
}: InspectorProps & { datasetName: string }) {
  const dataset = useQuery(getDatasetOptions({ path: { key: projectKey, name: datasetName } }));
  const nodeId = datasetNodeId(datasetName);

  return (
    <InspectorShell
      title={datasetName}
      kindLabel={dataset.data?.kind ?? "dataset"}
      badges={
        dataset.data ? (
          <ClassificationBadges
            classification={dataset.data.classification}
            bbnLevel={dataset.data.bbn_level}
            confidentiality={dataset.data.confidentiality}
          />
        ) : undefined
      }
      tab={tab}
      onTab={onTab}
      onClose={() => onSelectNode(null)}
    >
      <TabsContent value="configure">
        {dataset.isLoading ? (
          <LoadingBody />
        ) : dataset.isError || !dataset.data ? (
          <InspectorError onRetry={() => dataset.refetch()} error={dataset.error} />
        ) : (
          <DatasetConfigure projectKey={projectKey} dataset={dataset.data} canEdit={canEdit} />
        )}
      </TabsContent>

      <TabsContent value="preview">
        <DatasetPreviewTab projectKey={projectKey} datasetName={datasetName} />
      </TabsContent>

      <TabsContent value="runs">
        <RunsTab
          projectKey={projectKey}
          match={(step) => step.target_dataset_name === datasetName}
          onOpenJob={onOpenJob}
        />
      </TabsContent>

      <TabsContent value="lineage">
        <LineageTab flow={flow} nodeId={nodeId} onSelectNode={onSelectNode} />
      </TabsContent>

      <TabsContent value="docs">
        {dataset.data ? (
          <DatasetDocs projectKey={projectKey} dataset={dataset.data} canEdit={canEdit} />
        ) : (
          <LoadingBody />
        )}
      </TabsContent>
    </InspectorShell>
  );
}

function DatasetConfigure({
  projectKey,
  dataset,
  canEdit,
}: {
  projectKey: string;
  dataset: DatasetOut;
  canEdit: boolean;
}) {
  const queryClient = useQueryClient();
  const form = useForm<DatasetConfigValues>({
    resolver: zodResolver(datasetConfigSchema),
    defaultValues: {
      classification: dataset.classification as DatasetConfigValues["classification"],
      bbn_level: (dataset.bbn_level ?? "") as DatasetConfigValues["bbn_level"],
      confidentiality: (dataset.confidentiality ?? "") as DatasetConfigValues["confidentiality"],
      legal_basis: dataset.legal_basis,
      purpose_codes: dataset.purpose_codes.join(", "),
    },
  });
  const save = useMutation({
    mutationFn: (values: DatasetConfigValues) =>
      patchDataset({
        path: { key: projectKey, name: dataset.name },
        body: {
          classification: values.classification,
          bbn_level: values.bbn_level === "" ? null : values.bbn_level,
          confidentiality: values.confidentiality === "" ? null : values.confidentiality,
          legal_basis: values.legal_basis.trim(),
          purpose_codes: parsePurposeCodes(values.purpose_codes),
        },
        throwOnError: true,
      }),
    onSuccess: async (_response, values) => {
      await queryClient.invalidateQueries({
        queryKey: getDatasetQueryKey({ path: { key: projectKey, name: dataset.name } }),
      });
      await queryClient.invalidateQueries({ queryKey: listDatasetsQueryKey({ path: { key: projectKey } }) });
      await queryClient.invalidateQueries({ queryKey: getFlowQueryKey({ path: { key: projectKey } }) });
      form.reset(values);
      toast({ title: "Changes saved", severity: "success" });
    },
    onError: (error: unknown) => problemToast(error, "Couldn't save changes"),
  });
  const { errors } = form.formState;

  return (
    <form
      data-testid="dataset-inspector-configure"
      className="space-y-4"
      onSubmit={form.handleSubmit((values) => save.mutate(values))}
    >
      <div className="grid grid-cols-2 gap-2">
        <Field label="Classification" error={errors.classification?.message}>
          <NativeSelect disabled={!canEdit} {...form.register("classification")}>
            {CLASSIFICATIONS.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </NativeSelect>
        </Field>
        <Field label="BBN level" error={errors.bbn_level?.message}>
          <NativeSelect disabled={!canEdit} {...form.register("bbn_level")}>
            <option value="">not set</option>
            {BBN_LEVELS.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </NativeSelect>
        </Field>
      </div>
      <Field label="Confidentiality" error={errors.confidentiality?.message}>
        <NativeSelect disabled={!canEdit} {...form.register("confidentiality")}>
          <option value="">not set</option>
          {CONFIDENTIALITY_LEVELS.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </NativeSelect>
      </Field>
      <Field label="Legal basis" error={errors.legal_basis?.message}>
        <Input disabled={!canEdit} {...form.register("legal_basis")} />
      </Field>
      <Field label="Purpose codes" error={errors.purpose_codes?.message} hint="Comma-separated (CP-2)">
        <Input disabled={!canEdit} {...form.register("purpose_codes")} />
      </Field>
      {canEdit && (
        <Button
          type="submit"
          data-testid="dataset-inspector-save"
          loading={save.isPending}
          disabled={!form.formState.isDirty}
        >
          Save changes
        </Button>
      )}
    </form>
  );
}

function DatasetDocs({
  projectKey,
  dataset,
  canEdit,
}: {
  projectKey: string;
  dataset: DatasetOut;
  canEdit: boolean;
}) {
  const queryClient = useQueryClient();
  const form = useForm<{ description: string }>({
    defaultValues: { description: dataset.description },
  });
  const save = useMutation({
    mutationFn: (values: { description: string }) =>
      patchDataset({
        path: { key: projectKey, name: dataset.name },
        body: { description: values.description },
        throwOnError: true,
      }),
    onSuccess: async (_response, values) => {
      await queryClient.invalidateQueries({
        queryKey: getDatasetQueryKey({ path: { key: projectKey, name: dataset.name } }),
      });
      form.reset(values);
      toast({ title: "Changes saved", severity: "success" });
    },
    onError: (error: unknown) => problemToast(error, "Couldn't save changes"),
  });
  return (
    <form className="space-y-4" onSubmit={form.handleSubmit((values) => save.mutate(values))}>
      <Field label="Description">
        <textarea
          rows={4}
          disabled={!canEdit}
          className={TEXTAREA_CLASS}
          placeholder="What does this data describe?"
          {...form.register("description")}
        />
      </Field>
      {canEdit && (
        <Button
          type="submit"
          data-testid="dataset-docs-save"
          loading={save.isPending}
          disabled={!form.formState.isDirty}
        >
          Save changes
        </Button>
      )}
    </form>
  );
}

function DatasetPreviewTab({ projectKey, datasetName }: { projectKey: string; datasetName: string }) {
  const sampleQuery = useQuery(
    sampleDatasetOptions({ path: { key: projectKey, name: datasetName }, query: { limit: 50 } }),
  );

  if (sampleQuery.isLoading) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }
  if (sampleQuery.isError) {
    return (
      <EmptyState
        icon={<AlertTriangle aria-hidden className="size-8" />}
        title="Couldn't read a sample"
        description={asProblem(sampleQuery.error).hint ?? asProblem(sampleQuery.error).detail ?? "The source did not respond."}
      >
        <Button variant="secondary" onClick={() => sampleQuery.refetch()}>
          Retry
        </Button>
      </EmptyState>
    );
  }
  const rows = sampleQuery.data?.rows ?? [];
  if (rows.length === 0) {
    return <EmptyState title="No rows" description="The source returned an empty sample." />;
  }
  return (
    <PreviewGrid
      data-testid="dataset-inspector-preview"
      label={`Sample of ${datasetName}`}
      columns={sampleQuery.data?.columns ?? []}
      rows={rows}
    />
  );
}

// ── Runs + Lineage tabs ────────────────────────────────────────────────────────────

function RunsTab({
  projectKey,
  match,
  onOpenJob,
}: {
  projectKey: string;
  match: (step: StepOut) => boolean;
  onOpenJob: (jobId: string) => void;
}) {
  const jobs = useQuery(listJobsOptions({ path: { key: projectKey } }));

  if (jobs.isLoading) {
    return <Skeleton className="h-24 w-full" />;
  }
  if (jobs.isError) {
    return (
      <EmptyState
        icon={<AlertTriangle aria-hidden className="size-8" />}
        title="Couldn't load runs"
        description="The API did not respond."
      >
        <Button variant="secondary" onClick={() => jobs.refetch()}>
          Retry
        </Button>
      </EmptyState>
    );
  }
  const matching = (jobs.data?.items ?? []).filter((job) => job.steps.some(match));
  if (matching.length === 0) {
    return <EmptyState title="No runs yet" description="Build this node to see its run history here." />;
  }
  return (
    <ul className="space-y-1" data-testid="inspector-runs">
      {matching.map((job) => (
        <li key={job.id}>
          <button
            type="button"
            data-testid="inspector-run-row"
            onClick={() => onOpenJob(job.id)}
            className="flex w-full items-center gap-3 rounded-md border border-border px-3 py-2 text-left text-sm hover:bg-bg-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            <StatusDot status={job.status} />
            <span className="min-w-0 flex-1 truncate capitalize">{job.status}</span>
            <span className="shrink-0 text-xs text-faint">
              {new Date(job.created_at).toLocaleString()}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function LineageTab({
  flow,
  nodeId,
  onSelectNode,
}: {
  flow: FlowOut;
  nodeId: string;
  onSelectNode: (nodeId: string | null) => void;
}) {
  const { upstream, downstream } = neighbors(flow, nodeId);
  return (
    <div className="space-y-4" data-testid="inspector-lineage">
      <LineageGroup label="Upstream inputs" nodes={upstream} flow={flow} onSelectNode={onSelectNode} />
      <LineageGroup
        label="Downstream consumers"
        nodes={downstream}
        flow={flow}
        onSelectNode={onSelectNode}
      />
    </div>
  );
}

function LineageGroup({
  label,
  nodes,
  flow,
  onSelectNode,
}: {
  label: string;
  nodes: string[];
  flow: FlowOut;
  onSelectNode: (nodeId: string | null) => void;
}) {
  return (
    <div>
      <h3 className="text-xs font-medium uppercase tracking-wide text-faint">{label}</h3>
      {nodes.length === 0 ? (
        <p className="mt-1 text-sm text-muted">None.</p>
      ) : (
        <ul className="mt-2 space-y-1">
          {nodes.map((id) => (
            <li key={id}>
              <button
                type="button"
                onClick={() => onSelectNode(id)}
                className="flex w-full items-center gap-2 rounded-md border border-border px-3 py-1.5 text-left text-sm hover:bg-bg-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              >
                <ArrowUpRight aria-hidden className="size-3.5 text-faint" />
                <span className="min-w-0 flex-1 truncate">{nodeLabel(flow, id)}</span>
                <span className="shrink-0 text-xs text-faint">
                  {id.startsWith("recipe:") ? "recipe" : "dataset"}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ── Shared error ─────────────────────────────────────────────────────────────────

function InspectorError({ onRetry, error }: { onRetry: () => void; error: unknown }) {
  return (
    <EmptyState
      icon={<AlertTriangle aria-hidden className="size-8" />}
      title="Couldn't load this node"
      description={asProblem(error).hint ?? asProblem(error).detail ?? "It may have been removed."}
    >
      <Button variant="secondary" onClick={onRetry}>
        Retry
      </Button>
    </EmptyState>
  );
}
