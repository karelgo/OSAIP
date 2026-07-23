// Connections tab (settings): CP-2 governed source credentials. Admin-only writes
// (capabilities.can_manage_connections); viewers/editors get a read-only list.
// Creation/edit uses a non-modal side panel (§6.3(2)) — the CreateProjectPanel
// pattern; the modal is reserved for the destructive archive confirm.
import {
  Badge,
  Button,
  Checkbox,
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
  toast,
} from "@osaip/ui";
import {
  archiveConnection,
  createConnection,
  listConnectionsOptions,
  listConnectionsQueryKey,
  patchConnection,
  testConnection,
  type ConnectionOut,
  type ConnectionTestOut,
} from "@osaip/api-client";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Cable, KeyRound, Plus, X } from "lucide-react";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { NativeSelect } from "../../lib/NativeSelect";
import { problemToast } from "../../lib/problem";

const KINDS = ["postgres", "s3", "duckdb_file"] as const;
type ConnectionKind = (typeof KINDS)[number];

type PanelState = { mode: "create" } | { mode: "edit"; connection: ConnectionOut } | null;

export function ConnectionsTab({
  projectKey,
  canManage,
}: {
  projectKey: string;
  canManage: boolean;
}) {
  const queryClient = useQueryClient();
  const connections = useQuery(listConnectionsOptions({ path: { key: projectKey } }));
  const [panel, setPanel] = useState<PanelState>(null);

  async function refresh() {
    await queryClient.invalidateQueries({
      queryKey: listConnectionsQueryKey({ path: { key: projectKey } }),
    });
  }

  const test = useMutation({
    mutationFn: (connectionId: string) =>
      testConnection({
        path: { key: projectKey, connection_id: connectionId },
        throwOnError: true,
      }),
    onSuccess: (response) => {
      const result = response.data as ConnectionTestOut;
      if (result.ok) {
        toast({
          title: "Connection ok",
          description: `Reachable in ${result.latency_ms} ms`,
          severity: "success",
        });
      } else {
        toast({ title: "Connection failed", severity: "error" });
      }
    },
    onError: (error: unknown) => problemToast(error, "Connection test failed"),
  });

  const archive = useMutation({
    mutationFn: (connectionId: string) =>
      archiveConnection({
        path: { key: projectKey, connection_id: connectionId },
        throwOnError: true,
      }),
    onSuccess: async () => {
      await refresh();
      toast({ title: "Connection archived", severity: "info" });
    },
    onError: (error: unknown) => problemToast(error, "Couldn't archive the connection"),
  });

  const items = connections.data?.items ?? [];

  return (
    <div className="mt-4 flex items-start gap-6">
      <div className="min-w-0 flex-1 space-y-4">
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm text-muted">
            {canManage
              ? "Credentials for Postgres, S3, and DuckDB sources. Secrets are write-only and live in the vault."
              : "Read-only: only project admins manage connections."}
          </p>
          {canManage && (
            <Button data-testid="connection-create" onClick={() => setPanel({ mode: "create" })}>
              <Plus aria-hidden className="size-4" /> New connection
            </Button>
          )}
        </div>

        {connections.isLoading && <Skeleton className="h-40 w-full" />}

        {connections.isError && (
          <EmptyState
            icon={<AlertTriangle aria-hidden className="size-8" />}
            title="Couldn't load connections"
            description="The API did not respond. Check your connection, then retry."
          >
            <Button variant="secondary" onClick={() => connections.refetch()}>
              Retry
            </Button>
          </EmptyState>
        )}

        {connections.isSuccess && (
          // The testid sits on the container so the (possibly empty) list surface is
          // one stable target: table when populated, designed empty state otherwise.
          <div data-testid="connections-table">
            {items.length === 0 ? (
              <EmptyState
                icon={<Cable aria-hidden className="size-8" />}
                title="No connections yet"
                description={
                  canManage
                    ? "Connect Postgres, S3, or a DuckDB file so editors can register datasets from it."
                    : "A project admin can connect Postgres, S3, or a DuckDB file here."
                }
              >
                {canManage && (
                  <Button onClick={() => setPanel({ mode: "create" })}>
                    <Plus aria-hidden className="size-4" /> New connection
                  </Button>
                )}
              </EmptyState>
            ) : (
              <Table>
                <THead>
                  <TR>
                    <TH>Name</TH>
                    <TH>Kind</TH>
                    <TH>Purpose</TH>
                    <TH>Secret</TH>
                    <TH>Status</TH>
                    {canManage && <TH aria-label="Actions" />}
                  </TR>
                </THead>
                <TBody>
                  {items.map((connection) => (
                    <TR key={connection.id} data-testid="connection-row">
                      <TD className="font-medium">{connection.name}</TD>
                      <TD>
                        <Badge variant="neutral">{connection.kind}</Badge>
                      </TD>
                      <TD>
                        <span className="inline-flex flex-wrap gap-1">
                          {connection.purpose_codes.map((code) => (
                            <Badge key={code} variant="accent">
                              {code}
                            </Badge>
                          ))}
                        </span>
                      </TD>
                      <TD>
                        {connection.has_secret ? (
                          <Badge variant="neutral">
                            <KeyRound aria-hidden className="size-3" /> set
                          </Badge>
                        ) : (
                          <span className="text-faint">—</span>
                        )}
                      </TD>
                      <TD>
                        <Badge variant={connection.status === "active" ? "success" : "neutral"}>
                          {connection.status}
                        </Badge>
                      </TD>
                      {canManage && (
                        <TD>
                          <div className="flex justify-end gap-1">
                            <Button
                              variant="secondary"
                              size="sm"
                              data-testid="connection-test"
                              loading={test.isPending && test.variables === connection.id}
                              onClick={() => test.mutate(connection.id)}
                            >
                              Test
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              data-testid="connection-edit"
                              onClick={() => setPanel({ mode: "edit", connection })}
                            >
                              Edit
                            </Button>
                            <ConfirmDialog
                              title="Archive connection?"
                              description={`"${connection.name}" stops being available for new datasets.`}
                              confirmLabel="Archive connection"
                              destructive
                              onConfirm={() => archive.mutate(connection.id)}
                              trigger={
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  data-testid="connection-archive"
                                  aria-label={`Archive ${connection.name}`}
                                >
                                  Archive
                                </Button>
                              }
                            />
                          </div>
                        </TD>
                      )}
                    </TR>
                  ))}
                </TBody>
              </Table>
            )}
          </div>
        )}
      </div>

      {panel && canManage && (
        <ConnectionPanel
          projectKey={projectKey}
          connection={panel.mode === "edit" ? panel.connection : undefined}
          onClose={() => setPanel(null)}
          onSaved={refresh}
        />
      )}
    </div>
  );
}

// ── Create/edit panel ────────────────────────────────────────────────────────────

const schema = z
  .object({
    name: z.string().min(1, "Give the connection a name").max(200),
    kind: z.enum(KINDS),
    host: z.string(),
    port: z.string(),
    database: z.string(),
    user: z.string(),
    endpoint: z.string(),
    bucket: z.string(),
    region: z.string(),
    use_ssl: z.boolean(),
    access_key: z.string(),
    path: z.string(),
    secret: z.string(),
    legal_basis: z.string().min(1, "State the legal basis (CP-2)").max(500),
    purpose_codes: z
      .string()
      .refine((raw) => raw.split(",").some((code) => code.trim() !== ""), {
        message: "Give at least one purpose code (CP-2)",
      }),
  })
  .superRefine((values, ctx) => {
    const required: Array<[keyof typeof values, string]> =
      values.kind === "postgres"
        ? [
            ["host", "Host is required"],
            ["port", "Port is required"],
            ["database", "Database is required"],
            ["user", "User is required"],
          ]
        : values.kind === "s3"
          ? [
              ["endpoint", "Endpoint is required"],
              ["bucket", "Bucket is required"],
            ]
          : [["path", "Path is required"]];
    for (const [field, message] of required) {
      if (String(values[field]).trim() === "") {
        ctx.addIssue({ code: z.ZodIssueCode.custom, path: [field], message });
      }
    }
    if (values.kind === "postgres" && values.port.trim() !== "" && !/^\d+$/.test(values.port.trim())) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["port"], message: "Port must be a number" });
    }
  });

type FormValues = z.infer<typeof schema>;

function configFrom(values: FormValues): Record<string, unknown> {
  switch (values.kind) {
    case "postgres":
      return {
        host: values.host.trim(),
        port: Number(values.port.trim()),
        database: values.database.trim(),
        user: values.user.trim(),
      };
    case "s3":
      return {
        endpoint: values.endpoint.trim(),
        bucket: values.bucket.trim(),
        region: values.region.trim(),
        use_ssl: values.use_ssl,
        access_key: values.access_key.trim(),
      };
    case "duckdb_file":
      return { path: values.path.trim() };
  }
}

function purposeList(raw: string): string[] {
  return raw
    .split(",")
    .map((code) => code.trim())
    .filter(Boolean);
}

function ConnectionPanel({
  projectKey,
  connection,
  onClose,
  onSaved,
}: {
  projectKey: string;
  /** Set ⇒ edit mode; kind is immutable after creation. */
  connection?: ConnectionOut;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const idempotencyKey = useMemo(() => crypto.randomUUID(), []);
  const editing = connection !== undefined;
  const config = (connection?.config ?? {}) as Record<string, unknown>;

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: connection?.name ?? "",
      kind: (connection?.kind as ConnectionKind | undefined) ?? "postgres",
      host: String(config.host ?? ""),
      port: config.port !== undefined ? String(config.port) : "5432",
      database: String(config.database ?? ""),
      user: String(config.user ?? ""),
      endpoint: String(config.endpoint ?? ""),
      bucket: String(config.bucket ?? ""),
      region: String(config.region ?? ""),
      use_ssl: Boolean(config.use_ssl ?? true),
      access_key: String(config.access_key ?? ""),
      path: String(config.path ?? ""),
      secret: "",
      legal_basis: connection?.legal_basis ?? "",
      purpose_codes: connection?.purpose_codes.join(", ") ?? "",
    },
  });

  const kind = form.watch("kind");

  const save = useMutation({
    mutationFn: (values: FormValues) => {
      const body = {
        name: values.name,
        config: configFrom(values),
        legal_basis: values.legal_basis.trim(),
        purpose_codes: purposeList(values.purpose_codes),
        ...(values.secret !== "" ? { secret: values.secret } : {}),
      };
      return editing
        ? patchConnection({
            path: { key: projectKey, connection_id: connection.id },
            body,
            throwOnError: true,
          })
        : createConnection({
            path: { key: projectKey },
            body: { ...body, kind: values.kind },
            headers: { "Idempotency-Key": idempotencyKey },
            throwOnError: true,
          });
    },
    onSuccess: async () => {
      await onSaved();
      toast({
        title: editing ? "Changes saved" : "Connection created",
        severity: "success",
      });
      onClose();
    },
    onError: (error: unknown) =>
      problemToast(error, editing ? "Couldn't save changes" : "Couldn't create the connection"),
  });

  const { errors } = form.formState;
  const secretLabel = kind === "s3" ? "Secret key" : "Password";
  const secretHint = editing
    ? "Write-only. Leave blank to keep the current secret."
    : "Write-only: stored in the vault, never shown again.";

  return (
    <aside
      data-testid="connection-panel"
      aria-label={editing ? "Edit connection" : "New connection"}
      className="w-80 shrink-0 self-start rounded-lg border border-border bg-surface p-4 shadow-1"
    >
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">
          {editing ? "Edit connection" : "New connection"}
        </h2>
        <Button variant="ghost" size="sm" aria-label="Close panel" onClick={onClose}>
          <X aria-hidden className="size-4" />
        </Button>
      </div>
      <form
        className="mt-4 space-y-4"
        onSubmit={form.handleSubmit((values) => save.mutate(values))}
      >
        <Field label="Name" error={errors.name?.message}>
          <Input
            data-testid="connection-name-input"
            placeholder="warehouse"
            {...form.register("name")}
          />
        </Field>
        <Field
          label="Kind"
          hint={editing ? "The kind is fixed after creation." : undefined}
        >
          <NativeSelect disabled={editing} {...form.register("kind")}>
            {KINDS.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </NativeSelect>
        </Field>

        {kind === "postgres" && (
          <>
            <Field label="Host" error={errors.host?.message}>
              <Input placeholder="db.internal" {...form.register("host")} />
            </Field>
            <div className="grid grid-cols-2 gap-2">
              <Field label="Port" error={errors.port?.message}>
                <Input inputMode="numeric" placeholder="5432" {...form.register("port")} />
              </Field>
              <Field label="Database" error={errors.database?.message}>
                <Input placeholder="analytics" {...form.register("database")} />
              </Field>
            </div>
            <Field label="User" error={errors.user?.message}>
              <Input placeholder="reader" {...form.register("user")} />
            </Field>
          </>
        )}

        {kind === "s3" && (
          <>
            <Field label="Endpoint" error={errors.endpoint?.message}>
              <Input placeholder="https://s3.example.org" {...form.register("endpoint")} />
            </Field>
            <div className="grid grid-cols-2 gap-2">
              <Field label="Bucket" error={errors.bucket?.message}>
                <Input placeholder="data-lake" {...form.register("bucket")} />
              </Field>
              <Field label="Region" error={errors.region?.message}>
                <Input placeholder="eu-west-1" {...form.register("region")} />
              </Field>
            </div>
            <Field label="Access key" error={errors.access_key?.message}>
              <Input className="font-mono" {...form.register("access_key")} />
            </Field>
            <Checkbox
              label="Use SSL"
              checked={form.watch("use_ssl")}
              onCheckedChange={(checked) =>
                form.setValue("use_ssl", checked === true, { shouldDirty: true })
              }
            />
          </>
        )}

        {kind === "duckdb_file" && (
          <Field
            label="Path"
            error={errors.path?.message}
            hint="DuckDB file path inside project storage."
          >
            <Input className="font-mono" placeholder="files/reference.duckdb" {...form.register("path")} />
          </Field>
        )}

        {kind !== "duckdb_file" && (
          <Field label={secretLabel} error={errors.secret?.message} hint={secretHint}>
            <Input
              type="password"
              autoComplete="new-password"
              data-testid="connection-secret-input"
              {...form.register("secret")}
            />
          </Field>
        )}

        <Field label="Legal basis" error={errors.legal_basis?.message}>
          <Input
            data-testid="connection-legal-basis-input"
            placeholder="e.g. Art 6(1)(e) AVG"
            {...form.register("legal_basis")}
          />
        </Field>
        <Field
          label="Purpose codes"
          error={errors.purpose_codes?.message}
          hint="Comma-separated, e.g. demo, analytics"
        >
          <Input
            data-testid="connection-purpose-input"
            placeholder="demo, analytics"
            {...form.register("purpose_codes")}
          />
        </Field>

        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" data-testid="connection-save" loading={save.isPending}>
            {editing ? "Save changes" : "Create connection"}
          </Button>
        </div>
      </form>
    </aside>
  );
}
