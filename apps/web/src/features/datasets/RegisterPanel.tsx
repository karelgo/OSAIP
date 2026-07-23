// Register a dataset from an existing connection (§6.3(3), preview-first): pick a
// connection, name the table/path, inspect → typed schema + preview → confirm.
import { Button, Field, Input, Skeleton, toast } from "@osaip/ui";
import {
  createDataset,
  inspectConnection,
  listConnectionsOptions,
  listDatasetsQueryKey,
  type ConnectionOut,
  type InspectOut,
} from "@osaip/api-client";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { X } from "lucide-react";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { NativeSelect } from "../../lib/NativeSelect";
import { asProblem, problemToast } from "../../lib/problem";
import { DatasetMetaFields } from "./MetaFields";
import { SchemaPreview } from "./SchemaPreview";
import { datasetMetaSchema, slugifyName, toDatasetMeta, type DatasetMetaValues } from "./lib";

// connection kind → DatasetCreate source kind
const SOURCE_KIND = { postgres: "table", s3: "s3", duckdb_file: "duckdb_file" } as const;

export function RegisterPanel({
  projectKey,
  onClose,
}: {
  projectKey: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const idempotencyKey = useMemo(() => crypto.randomUUID(), []);

  const connections = useQuery(listConnectionsOptions({ path: { key: projectKey } }));
  const [connectionId, setConnectionId] = useState("");
  const [table, setTable] = useState("");
  const [path, setPath] = useState("");

  const items = (connections.data?.items ?? []).filter(
    (connection) => connection.status === "active",
  );
  const selected: ConnectionOut | undefined = items.find((item) => item.id === connectionId);
  const needsPath = selected?.kind === "s3";

  const inspect = useMutation({
    mutationFn: () =>
      inspectConnection({
        path: { key: projectKey, connection_id: connectionId },
        body: needsPath ? { path } : { table },
        throwOnError: true,
      }),
    onSuccess: () => {
      if (!form.formState.dirtyFields.name) {
        form.setValue("name", slugifyName(needsPath ? path.split("/").pop() ?? path : table));
      }
    },
  });

  const form = useForm<DatasetMetaValues>({
    resolver: zodResolver(datasetMetaSchema),
    defaultValues: {
      name: "",
      description: "",
      classification: "none",
      bbn_level: "",
      confidentiality: "",
      legal_basis: "",
      purpose_codes: "",
    },
  });

  const create = useMutation({
    mutationFn: (values: DatasetMetaValues) => {
      const kind = SOURCE_KIND[selected?.kind as keyof typeof SOURCE_KIND];
      return createDataset({
        path: { key: projectKey },
        body: {
          ...toDatasetMeta(values),
          source: {
            kind,
            connection_id: connectionId,
            ...(needsPath ? { path } : { table }),
          },
        },
        headers: { "Idempotency-Key": idempotencyKey },
        throwOnError: true,
      });
    },
    onSuccess: async (response) => {
      await queryClient.invalidateQueries({
        queryKey: listDatasetsQueryKey({ path: { key: projectKey } }),
      });
      toast({ title: "Dataset registered", severity: "success" });
      void navigate({
        to: "/p/$key/datasets/$datasetName",
        params: { key: projectKey, datasetName: response.data.name },
      });
    },
    onError: (error: unknown) => problemToast(error, "Couldn't register the dataset"),
  });

  const inspectResult = inspect.data?.data as InspectOut | undefined;
  const inspectProblem = inspect.isError ? asProblem(inspect.error) : null;
  const locator = needsPath ? path.trim() : table.trim();

  return (
    <aside
      data-testid="register-panel"
      aria-label="Register from connection"
      className="w-[26rem] shrink-0 self-start rounded-lg border border-border bg-surface p-4 shadow-1"
    >
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">Register from connection</h2>
        <Button variant="ghost" size="sm" aria-label="Close panel" onClick={onClose}>
          <X aria-hidden className="size-4" />
        </Button>
      </div>

      <div className="mt-4 space-y-4">
        {connections.isLoading && <Skeleton className="h-16 w-full" />}
        {connections.isSuccess && items.length === 0 && (
          <p className="text-sm text-muted">
            No active connections in this project yet. A project admin can add one under
            Settings → Connections.
          </p>
        )}
        {items.length > 0 && (
          <>
            <Field label="Connection" hint="Postgres, S3, or DuckDB file — added in project settings.">
              <NativeSelect
                data-testid="register-connection-select"
                value={connectionId}
                onChange={(event) => {
                  setConnectionId(event.target.value);
                  inspect.reset();
                }}
              >
                <option value="">Pick a connection…</option>
                {items.map((connection) => (
                  <option key={connection.id} value={connection.id}>
                    {connection.name}
                  </option>
                ))}
              </NativeSelect>
            </Field>

            {selected && !needsPath && (
              <Field
                label="Table"
                hint={selected.kind === "postgres" ? "schema.table, e.g. public.sales" : "Table inside the DuckDB file"}
              >
                <Input
                  data-testid="register-table-input"
                  className="font-mono"
                  placeholder="public.sales"
                  value={table}
                  onChange={(event) => {
                    setTable(event.target.value);
                    inspect.reset();
                  }}
                />
              </Field>
            )}
            {selected && needsPath && (
              <Field label="Path" hint="Parquet path inside the bucket, e.g. exports/sales.parquet">
                <Input
                  data-testid="register-path-input"
                  className="font-mono"
                  placeholder="exports/sales.parquet"
                  value={path}
                  onChange={(event) => {
                    setPath(event.target.value);
                    inspect.reset();
                  }}
                />
              </Field>
            )}

            <Button
              type="button"
              variant="secondary"
              data-testid="register-inspect"
              disabled={!selected || locator === ""}
              loading={inspect.isPending}
              onClick={() => inspect.mutate()}
            >
              Preview
            </Button>

            {inspectProblem && (
              <div role="alert" className="rounded-md border border-status-danger/40 p-3 text-sm">
                <p className="font-medium">{inspectProblem.title ?? "Couldn't read the source"}</p>
                {inspectProblem.detail && (
                  <p className="mt-1 text-muted">{inspectProblem.detail}</p>
                )}
                {inspectProblem.hint && <p className="mt-1 text-muted">{inspectProblem.hint}</p>}
              </div>
            )}

            {inspectResult && (
              <>
                <SchemaPreview
                  columns={inspectResult.columns}
                  preview={inspectResult.preview}
                  testId="register-preview"
                />
                <form
                  className="space-y-4"
                  onSubmit={form.handleSubmit((values) => create.mutate(values))}
                >
                  <DatasetMetaFields
                    form={form}
                    cp2Hint="Left empty, this is inherited from the connection (CP-2)."
                  />
                  <div className="flex justify-end gap-2">
                    <Button type="button" variant="ghost" onClick={onClose}>
                      Cancel
                    </Button>
                    <Button
                      type="submit"
                      data-testid="dataset-register-confirm"
                      loading={create.isPending}
                    >
                      Register dataset
                    </Button>
                  </div>
                </form>
              </>
            )}
          </>
        )}
      </div>
    </aside>
  );
}
