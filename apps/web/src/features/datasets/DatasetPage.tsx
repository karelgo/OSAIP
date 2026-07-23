// Dataset detail (/p/$key/datasets/$datasetName): Schema · Sample · Profile ·
// Configure — the inspector tab pattern (§6.3(2)), deep-linkable via ?tab= (§6.7).
import {
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  Field,
  Input,
  Skeleton,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  toast,
} from "@osaip/ui";
import {
  archiveDataset,
  getDatasetOptions,
  getDatasetQueryKey,
  getFlowOptions,
  getProfileOptions,
  getProfileQueryKey,
  getProjectOptions,
  listDatasetsQueryKey,
  patchDataset,
  recomputeProfile,
  sampleDatasetOptions,
  type DatasetOut,
} from "@osaip/api-client";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { AlertTriangle, Archive, ArrowUpRight, BarChart3, GitBranch } from "lucide-react";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { NativeSelect } from "../../lib/NativeSelect";
import { PlainTable, STICKY_THEAD, ScrollRegion } from "../../lib/ScrollRegion";
import { asProblem, problemToast } from "../../lib/problem";
import { datasetNodeId, neighbors, nodeLabel, parseSelection } from "../flow/graph";
import {
  BBN_LEVELS,
  CLASSIFICATIONS,
  CONFIDENTIALITY_LEVELS,
  ClassificationBadges,
  formatRowCount,
  formatValue,
  parsePurposeCodes,
} from "./lib";

type DatasetTab = "schema" | "sample" | "profile" | "lineage" | "configure";

const ROUTE_ID = "/_authed/_shell/p/$key/datasets/$datasetName";

export function DatasetPage() {
  const { key, datasetName } = useParams({ from: ROUTE_ID });
  const search = useSearch({ from: ROUTE_ID });
  const navigate = useNavigate();
  const project = useQuery(getProjectOptions({ path: { key } }));
  const dataset = useQuery(getDatasetOptions({ path: { key, name: datasetName } }));

  if (dataset.isLoading) {
    return (
      <div className="p-6" data-testid="dataset-loading">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="mt-4 h-64 w-full" />
      </div>
    );
  }
  if (dataset.isError || !dataset.data) {
    return (
      <div className="flex h-full items-center justify-center p-8">
        <EmptyState
          icon={<AlertTriangle aria-hidden className="size-8" />}
          title="Couldn't load this dataset"
          description="It may have been archived, or you may not have access to this project."
        >
          <Button variant="secondary" onClick={() => dataset.refetch()}>
            Retry
          </Button>
        </EmptyState>
      </div>
    );
  }

  const data = dataset.data;
  const canEdit = project.data?.capabilities.can_edit ?? false;
  const tab: DatasetTab = search.tab ?? "schema";

  function setTab(next: string) {
    void navigate({
      to: "/p/$key/datasets/$datasetName",
      params: { key, datasetName },
      search: next === "schema" ? {} : { tab: next as DatasetTab },
      replace: true,
    });
  }

  return (
    <div className="mx-auto max-w-5xl p-6" data-testid="dataset-page">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold tracking-tight">{data.name}</h1>
        <Badge variant="neutral">{data.kind}</Badge>
        <ClassificationBadges
          classification={data.classification}
          bbnLevel={data.bbn_level}
          confidentiality={data.confidentiality}
        />
        <Badge variant="accent" className="font-mono">
          v{data.current_version}
        </Badge>
      </div>
      <p className="mt-1 text-sm text-muted">
        {formatRowCount(data.row_count, data.row_count_kind)} rows
        {data.row_count_kind === "estimate" ? " (estimate)" : ""} · updated{" "}
        {new Date(data.updated_at).toLocaleString()}
        {data.description ? ` — ${data.description}` : ""}
      </p>

      <Tabs value={tab} onValueChange={setTab} className="mt-6">
        <TabsList>
          <TabsTrigger value="schema" data-testid="dataset-tab-schema">
            Schema
          </TabsTrigger>
          <TabsTrigger value="sample" data-testid="dataset-tab-sample">
            Sample
          </TabsTrigger>
          <TabsTrigger value="profile" data-testid="dataset-tab-profile">
            Profile
          </TabsTrigger>
          <TabsTrigger value="lineage" data-testid="dataset-tab-lineage">
            Lineage
          </TabsTrigger>
          <TabsTrigger value="configure" data-testid="dataset-tab-configure">
            Configure
          </TabsTrigger>
        </TabsList>
        <TabsContent value="schema">
          <SchemaTab projectKey={key} dataset={data} canEdit={canEdit} />
        </TabsContent>
        <TabsContent value="sample">
          <SampleTab projectKey={key} datasetName={data.name} />
        </TabsContent>
        <TabsContent value="profile">
          <ProfileTab projectKey={key} dataset={data} canEdit={canEdit} />
        </TabsContent>
        <TabsContent value="lineage">
          <LineageTab projectKey={key} datasetName={data.name} />
        </TabsContent>
        <TabsContent value="configure">
          <ConfigureTab projectKey={key} dataset={data} canEdit={canEdit} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

// ── Schema ───────────────────────────────────────────────────────────────────────

function SchemaTab({
  projectKey,
  dataset,
  canEdit,
}: {
  projectKey: string;
  dataset: DatasetOut;
  canEdit: boolean;
}) {
  const queryClient = useQueryClient();

  const label = useMutation({
    mutationFn: ({ column, value }: { column: string; value: string }) =>
      patchDataset({
        path: { key: projectKey, name: dataset.name },
        body: { column_classifications: { [column]: value } },
        throwOnError: true,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: getDatasetQueryKey({ path: { key: projectKey, name: dataset.name } }),
      });
    },
    onError: (error: unknown) => problemToast(error, "Couldn't label the column"),
  });

  return (
    <Table data-testid="dataset-schema-table">
      <THead>
        <TR>
          <TH>Column</TH>
          <TH>Type</TH>
          <TH>Nullable</TH>
          <TH>Classification</TH>
        </TR>
      </THead>
      <TBody>
        {dataset.columns.map((column) => (
          <TR key={column.name}>
            <TD className="font-mono text-xs">{column.name}</TD>
            <TD className="font-mono text-xs text-muted">{column.type}</TD>
            <TD className="text-muted">{column.nullable === false ? "no" : "yes"}</TD>
            <TD>
              {canEdit ? (
                <NativeSelect
                  className="h-7 w-44 rounded-sm px-2 text-xs"
                  aria-label={`Classification for ${column.name}`}
                  value={column.classification ?? "none"}
                  disabled={label.isPending}
                  onChange={(event) =>
                    label.mutate({ column: column.name, value: event.target.value })
                  }
                >
                  {CLASSIFICATIONS.map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </NativeSelect>
              ) : (
                <Badge variant={column.classification === "none" ? "neutral" : "warning"}>
                  {column.classification ?? "none"}
                </Badge>
              )}
            </TD>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}

// ── Sample ───────────────────────────────────────────────────────────────────────

function SampleTab({ projectKey, datasetName }: { projectKey: string; datasetName: string }) {
  const [limit, setLimit] = useState(100);
  const sample = useQuery(
    sampleDatasetOptions({ path: { key: projectKey, name: datasetName }, query: { limit } }),
  );

  const rows = useMemo(() => sample.data?.rows ?? [], [sample.data]);
  const columns = useMemo<Array<ColumnDef<Record<string, unknown>>>>(
    () =>
      (sample.data?.columns ?? []).map((column) => ({
        id: column.name,
        header: column.name,
        accessorFn: (row: Record<string, unknown>) => row[column.name],
        cell: (info) => formatValue(info.getValue()),
      })),
    [sample.data],
  );

  const table = useReactTable({ data: rows, columns, getCoreRowModel: getCoreRowModel() });

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-end gap-2">
        <label htmlFor="sample-limit" className="text-sm text-muted">
          Sample size
        </label>
        <NativeSelect
          id="sample-limit"
          data-testid="dataset-sample-limit"
          className="w-24"
          value={String(limit)}
          onChange={(event) => setLimit(Number(event.target.value))}
        >
          {[10, 100, 1000].map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </NativeSelect>
      </div>

      {sample.isLoading && (
        <div className="space-y-2" data-testid="dataset-sample-loading">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      )}
      {sample.isError && (
        <EmptyState
          icon={<AlertTriangle aria-hidden className="size-8" />}
          title="Couldn't read a sample"
          description={
            asProblem(sample.error).hint ??
            asProblem(sample.error).detail ??
            "The source did not respond."
          }
        >
          <Button variant="secondary" onClick={() => sample.refetch()}>
            Retry
          </Button>
        </EmptyState>
      )}
      {sample.isSuccess && rows.length === 0 && (
        <EmptyState title="No rows" description="The source returned an empty sample." />
      )}
      {sample.isSuccess && rows.length > 0 && (
        <ScrollRegion
          label="Sample rows"
          data-testid="dataset-sample-table"
          className="max-h-[32rem] rounded-md border border-border"
        >
          <PlainTable>
            <THead className={STICKY_THEAD}>
              {table.getHeaderGroups().map((headerGroup) => (
                <TR key={headerGroup.id}>
                  {headerGroup.headers.map((header) => (
                    <TH key={header.id} className="whitespace-nowrap font-mono text-xs">
                      {flexRender(header.column.columnDef.header, header.getContext())}
                    </TH>
                  ))}
                </TR>
              ))}
            </THead>
            <TBody>
              {table.getRowModel().rows.map((row) => (
                <TR key={row.id}>
                  {row.getVisibleCells().map((cell) => (
                    <TD key={cell.id} className="whitespace-nowrap font-mono text-xs tabular-nums">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TD>
                  ))}
                </TR>
              ))}
            </TBody>
          </PlainTable>
        </ScrollRegion>
      )}
    </div>
  );
}

// ── Profile ──────────────────────────────────────────────────────────────────────

interface ProfileColumn {
  name: string;
  type: string;
  null_count: number;
  distinct_approx: number;
  min?: unknown;
  max?: unknown;
  mean?: unknown;
  top_values?: Array<{ value: unknown; count: number }>;
}

interface ProfileData {
  row_count: number;
  columns: ProfileColumn[];
}

function ProfileTab({
  projectKey,
  dataset,
  canEdit,
}: {
  projectKey: string;
  dataset: DatasetOut;
  canEdit: boolean;
}) {
  const queryClient = useQueryClient();

  // Stored profiles are read through the viewer-accessible GET endpoint; the POST
  // stays editor-only for recomputes.
  const profile = useQuery({
    ...getProfileOptions({ path: { key: projectKey, name: dataset.name } }),
    enabled: dataset.has_profile,
    retry: false,
  });
  const [recomputing, setRecomputing] = useState(false);

  async function recompute() {
    setRecomputing(true);
    try {
      await recomputeProfile({
        path: { key: projectKey, name: dataset.name },
        throwOnError: true,
      });
      await queryClient.invalidateQueries({
        queryKey: getProfileQueryKey({ path: { key: projectKey, name: dataset.name } }),
      });
      // row_count/row_count_kind may have changed (exact after profiling)
      await queryClient.invalidateQueries({
        queryKey: getDatasetQueryKey({ path: { key: projectKey, name: dataset.name } }),
      });
    } catch (error) {
      problemToast(error, "Couldn't compute the profile");
    } finally {
      setRecomputing(false);
    }
  }

  if (!dataset.has_profile && !canEdit) {
    return (
      <EmptyState
        icon={<BarChart3 aria-hidden className="size-8" />}
        title="No profile yet"
        description="A project editor can compute per-column statistics for this dataset."
      />
    );
  }

  if (!dataset.has_profile && !recomputing && !profile.data) {
    return (
      <EmptyState
        icon={<BarChart3 aria-hidden className="size-8" />}
        title="No profile yet"
        description="Compute per-column statistics: null counts, distinct estimates, ranges, and top values."
      >
        <Button data-testid="profile-recompute" onClick={() => void recompute()}>
          Compute profile
        </Button>
      </EmptyState>
    );
  }

  if ((profile.isFetching || recomputing) && !profile.data) {
    return (
      <div className="space-y-2" data-testid="dataset-profile-loading">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-full" />
      </div>
    );
  }

  if (profile.isError && !profile.data) {
    return (
      <EmptyState
        icon={<AlertTriangle aria-hidden className="size-8" />}
        title="Couldn't compute the profile"
        description={
          asProblem(profile.error).hint ??
          asProblem(profile.error).detail ??
          "The source did not respond."
        }
      >
        <Button variant="secondary" data-testid="profile-recompute" onClick={() => void recompute()}>
          Retry
        </Button>
      </EmptyState>
    );
  }

  const parsed = profile.data?.profile as unknown as ProfileData | undefined;
  if (!parsed || !Array.isArray(parsed.columns)) return null;

  return (
    <div className="space-y-3" data-testid="dataset-profile">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted">
          {parsed.row_count.toLocaleString()} rows profiled ·{" "}
          {parsed.columns.length} columns
        </p>
        <Button
          variant="secondary"
          size="sm"
          data-testid="profile-recompute"
          loading={profile.isFetching}
          onClick={() => void recompute()}
        >
          Recompute
        </Button>
      </div>
      <Table>
        <THead>
          <TR>
            <TH>Column</TH>
            <TH numeric>Nulls</TH>
            <TH numeric>Distinct (approx)</TH>
            <TH>Range / top values</TH>
          </TR>
        </THead>
        <TBody>
          {parsed.columns.map((column) => (
            <TR key={column.name}>
              <TD>
                <span className="font-mono text-xs">{column.name}</span>
                <span className="ml-2 font-mono text-xs text-faint">{column.type}</span>
              </TD>
              <TD numeric className="tabular-nums">
                {column.null_count.toLocaleString()}
              </TD>
              <TD numeric className="tabular-nums">
                {column.distinct_approx.toLocaleString()}
              </TD>
              <TD>
                {column.top_values ? (
                  <TopValueBars values={column.top_values} />
                ) : (
                  <span className="font-mono text-xs tabular-nums text-muted">
                    {formatValue(column.min)} – {formatValue(column.max)}
                    {column.mean !== undefined ? ` · mean ${formatMean(column.mean)}` : ""}
                  </span>
                )}
              </TD>
            </TR>
          ))}
        </TBody>
      </Table>
    </div>
  );
}

function formatMean(mean: unknown): string {
  return typeof mean === "number" ? mean.toLocaleString(undefined, { maximumFractionDigits: 2 }) : formatValue(mean);
}

function TopValueBars({ values }: { values: Array<{ value: unknown; count: number }> }) {
  const max = Math.max(1, ...values.map((entry) => entry.count));
  return (
    <div className="max-w-xs space-y-1">
      {values.map((entry, index) => (
        <div key={index} className="flex items-center gap-2">
          <span className="w-24 truncate font-mono text-xs" title={formatValue(entry.value)}>
            {formatValue(entry.value)}
          </span>
          <div className="h-1.5 flex-1 overflow-hidden rounded-sm bg-bg-subtle">
            <div
              className="h-full rounded-sm bg-accent"
              style={{ width: `${Math.round((entry.count / max) * 100)}%` }}
            />
          </div>
          <span className="w-10 text-right font-mono text-xs tabular-nums text-muted">
            {entry.count.toLocaleString()}
          </span>
        </div>
      ))}
    </div>
  );
}

// ── Lineage ──────────────────────────────────────────────────────────────────────

function LineageTab({ projectKey, datasetName }: { projectKey: string; datasetName: string }) {
  const flow = useQuery(getFlowOptions({ path: { key: projectKey } }));

  if (flow.isLoading) {
    return (
      <div className="space-y-2" data-testid="dataset-lineage-loading">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-full" />
      </div>
    );
  }
  if (flow.isError || !flow.data) {
    return (
      <EmptyState
        icon={<AlertTriangle aria-hidden className="size-8" />}
        title="Couldn't load lineage"
        description={asProblem(flow.error).hint ?? asProblem(flow.error).detail ?? "The API did not respond."}
      >
        <Button variant="secondary" onClick={() => flow.refetch()}>
          Retry
        </Button>
      </EmptyState>
    );
  }

  const nodeId = datasetNodeId(datasetName);
  const { upstream, downstream } = neighbors(flow.data, nodeId);
  const isProduced = upstream.length > 0;

  return (
    <div className="max-w-2xl space-y-6" data-testid="dataset-lineage">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-muted">
          {isProduced
            ? "This dataset is built by a recipe."
            : "This dataset is a source — no recipe produces it."}
        </p>
        <Link
          to="/p/$key"
          params={{ key: projectKey }}
          search={{ sel: nodeId }}
          className="inline-flex items-center gap-1 text-sm text-accent-strong underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          <GitBranch aria-hidden className="size-3.5" /> Open in Flow
        </Link>
      </div>

      <LineageColumn
        label="Produced by"
        emptyLabel="No producing recipe — this is a source dataset."
        nodes={upstream}
        flow={flow.data}
        projectKey={projectKey}
      />
      <LineageColumn
        label="Consumed by"
        emptyLabel="No recipe consumes this dataset yet."
        nodes={downstream}
        flow={flow.data}
        projectKey={projectKey}
      />
    </div>
  );
}

function LineageColumn({
  label,
  emptyLabel,
  nodes,
  flow,
  projectKey,
}: {
  label: string;
  emptyLabel: string;
  nodes: string[];
  flow: import("@osaip/api-client").FlowOut;
  projectKey: string;
}) {
  return (
    <div>
      <h3 className="text-xs font-medium uppercase tracking-wide text-faint">{label}</h3>
      {nodes.length === 0 ? (
        <p className="mt-1 text-sm text-muted">{emptyLabel}</p>
      ) : (
        <ul className="mt-2 space-y-1">
          {nodes.map((id) => {
            const selection = parseSelection(id);
            return (
              <li key={id}>
                <Link
                  to="/p/$key"
                  params={{ key: projectKey }}
                  search={{ sel: id }}
                  className="flex items-center gap-2 rounded-md border border-border px-3 py-1.5 text-sm hover:bg-bg-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                >
                  <ArrowUpRight aria-hidden className="size-3.5 text-faint" />
                  <span className="min-w-0 flex-1 truncate">{nodeLabel(flow, id)}</span>
                  <span className="shrink-0 text-xs text-faint">
                    {selection?.kind === "recipe" ? "recipe" : "dataset"}
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

// ── Configure ────────────────────────────────────────────────────────────────────

const configureSchema = z.object({
  description: z.string().max(10_000),
  classification: z.enum(["none", "persoonsgegevens", "bijzonder", "bsn"]),
  bbn_level: z.enum(["", "bbn1", "bbn2", "bbn3"]),
  confidentiality: z.enum(["", "intern", "vertrouwelijk", "geheim"]),
  legal_basis: z.string().min(1, "State the legal basis (CP-2)").max(500),
  purpose_codes: z.string().refine((raw) => parsePurposeCodes(raw).length > 0, {
    message: "Give at least one purpose code (CP-2)",
  }),
});

type ConfigureValues = z.infer<typeof configureSchema>;

function ConfigureTab({
  projectKey,
  dataset,
  canEdit,
}: {
  projectKey: string;
  dataset: DatasetOut;
  canEdit: boolean;
}) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const form = useForm<ConfigureValues>({
    resolver: zodResolver(configureSchema),
    defaultValues: {
      description: dataset.description,
      classification: dataset.classification as ConfigureValues["classification"],
      bbn_level: (dataset.bbn_level ?? "") as ConfigureValues["bbn_level"],
      confidentiality: (dataset.confidentiality ?? "") as ConfigureValues["confidentiality"],
      legal_basis: dataset.legal_basis,
      purpose_codes: dataset.purpose_codes.join(", "),
    },
  });

  const save = useMutation({
    mutationFn: (values: ConfigureValues) =>
      patchDataset({
        path: { key: projectKey, name: dataset.name },
        body: {
          description: values.description,
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
      await queryClient.invalidateQueries({
        queryKey: listDatasetsQueryKey({ path: { key: projectKey } }),
      });
      form.reset(values);
      toast({ title: "Changes saved", severity: "success" });
    },
    onError: (error: unknown) => problemToast(error, "Couldn't save changes"),
  });

  const archive = useMutation({
    mutationFn: () =>
      archiveDataset({ path: { key: projectKey, name: dataset.name }, throwOnError: true }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: listDatasetsQueryKey({ path: { key: projectKey } }),
      });
      toast({ title: "Dataset archived", severity: "info" });
      void navigate({ to: "/p/$key/datasets", params: { key: projectKey } });
    },
    onError: (error: unknown) => problemToast(error, "Couldn't archive the dataset"),
  });

  const { errors } = form.formState;

  return (
    <div className="max-w-2xl space-y-6" data-testid="dataset-configure">
      <form
        className="space-y-4"
        onSubmit={form.handleSubmit((values) => save.mutate(values))}
      >
        <Field label="Description" error={errors.description?.message}>
          <textarea
            rows={3}
            disabled={!canEdit}
            className="flex w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-fg transition-colors duration-fast placeholder:text-faint focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg disabled:cursor-not-allowed disabled:opacity-50"
            placeholder="What does this data describe?"
            {...form.register("description")}
          />
        </Field>
        <div className="grid grid-cols-3 gap-2">
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
        </div>
        <Field label="Legal basis" error={errors.legal_basis?.message}>
          <Input disabled={!canEdit} {...form.register("legal_basis")} />
        </Field>
        <Field
          label="Purpose codes"
          error={errors.purpose_codes?.message}
          hint="Comma-separated, e.g. demo, analytics"
        >
          <Input disabled={!canEdit} {...form.register("purpose_codes")} />
        </Field>
        {canEdit && (
          <Button
            type="submit"
            data-testid="dataset-save"
            loading={save.isPending}
            disabled={!form.formState.isDirty}
          >
            Save changes
          </Button>
        )}
      </form>

      {canEdit && (
        <div className="rounded-lg border border-status-danger/40 p-4">
          <h3 className="text-sm font-medium">Archive this dataset</h3>
          <p className="mt-1 text-sm text-muted">
            Archived datasets leave the list and search. The stored versions are kept.
          </p>
          <ConfirmDialog
            title="Archive dataset?"
            description={`"${dataset.name}" becomes unavailable to this project's flows.`}
            confirmLabel="Archive dataset"
            destructive
            onConfirm={() => archive.mutate()}
            trigger={
              <Button variant="danger" className="mt-3" data-testid="dataset-archive">
                <Archive aria-hidden className="size-4" /> Archive dataset
              </Button>
            }
          />
        </div>
      )}
    </div>
  );
}
