// LLM connections tab (settings): the endpoints the mesh may call, and the budgets
// that bound them. Admin-only writes (capabilities.can_manage_connections); everyone
// else gets a read-only list, because which models a project can use is not a secret.
//
// Two things this UI is careful about, because getting them wrong is a compliance
// event rather than a bug:
//   · data_residency is OPERATOR-ASSERTED. The form says so in words, not a tooltip.
//   · audit_mode=full retains raw prompt text. Choosing it shows what that means.
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
  toast,
} from "@osaip/ui";
import {
  archiveProjectConnection,
  createProjectConnection,
  createQuota,
  deleteQuota,
  listProjectConnections,
  listProjectConnectionsOptions,
  listProjectConnectionsQueryKey,
  listQuotasOptions,
  listQuotasQueryKey,
  testProjectConnection,
  updateProjectConnection,
} from "@osaip/api-client";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Bot, Gauge, KeyRound, Plus, ShieldAlert, X } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { NativeSelect } from "../../lib/NativeSelect";
import { problemToast } from "../../lib/problem";

const PROVIDERS = ["echo", "openai", "anthropic", "ollama"] as const;
const RESIDENCIES = ["local", "eu", "external"] as const;
const AUDIT_MODES = ["redacted", "full", "off"] as const;

// Mirrors the server rule (llm_connections._check_residency) so the form can explain
// the constraint before the request, rather than surfacing a 422 the user must decode.
const HOSTED = new Set(["openai", "anthropic"]);

type LlmConnection = {
  id: string;
  name: string;
  provider: string;
  data_residency: string;
  audit_mode: string;
  allowed_models: string[];
  cache_ttl_s: number;
  legal_basis: string;
  purpose_codes: string[];
  has_secret: boolean;
  scope: string;
  status: string;
};

const schema = z
  .object({
    name: z.string().min(1, "Name is required").max(200),
    provider: z.enum(PROVIDERS),
    data_residency: z.enum(RESIDENCIES),
    audit_mode: z.enum(AUDIT_MODES),
    allowed_models: z.string(),
    base_url: z.string(),
    cache_ttl_s: z.coerce.number().int().min(0).max(86_400),
    legal_basis: z.string().min(1, "A legal basis is required (CP-2)"),
    purpose_codes: z.string().min(1, "At least one purpose code is required (CP-2)"),
    secret: z.string(),
  })
  .refine((v) => !HOSTED.has(v.provider) || v.data_residency === "external", {
    path: ["data_residency"],
    message: "A hosted vendor runs outside your boundary — declare it external.",
  })
  .refine((v) => v.provider !== "echo" || v.data_residency === "local", {
    path: ["data_residency"],
    message: "Echo is a built-in mock; it is always local.",
  });

type FormValues = z.input<typeof schema>;

type PanelState = { mode: "create" } | { mode: "edit"; connection: LlmConnection } | null;

export function LlmConnectionsTab({
  projectKey,
  canManage,
}: {
  projectKey: string;
  canManage: boolean;
}) {
  const queryClient = useQueryClient();
  const connections = useQuery(listProjectConnectionsOptions({ path: { key: projectKey } }));
  const [panel, setPanel] = useState<PanelState>(null);
  const [confirmArchive, setConfirmArchive] = useState<LlmConnection | null>(null);

  async function refresh() {
    await queryClient.invalidateQueries({
      queryKey: listProjectConnectionsQueryKey({ path: { key: projectKey } }),
    });
  }

  const test = useMutation({
    mutationFn: (connectionId: string) =>
      testProjectConnection({
        path: { key: projectKey, connection_id: connectionId },
        throwOnError: true,
      }),
    onSuccess: (response) => {
      const result = response.data as {
        ok: boolean;
        detail?: string;
        model_version?: string;
        tokens_in?: number;
        cost_micros?: number;
      };
      if (result.ok) {
        toast({
          title: "Connection works",
          description: `Served by ${result.model_version ?? "the provider"} · ${result.tokens_in ?? 0} tokens in`,
          severity: "success",
        });
      } else {
        // A failed test is a RESULT, not an error: the call went through the mesh and
        // came back with a verdict worth reading.
        toast({ title: "Connection test failed", description: result.detail, severity: "error" });
      }
    },
    onError: (error: unknown) => problemToast(error, "Connection test failed"),
  });

  const archive = useMutation({
    mutationFn: (connectionId: string) =>
      archiveProjectConnection({
        path: { key: projectKey, connection_id: connectionId },
        throwOnError: true,
      }),
    onSuccess: async () => {
      toast({ title: "Connection archived", severity: "info" });
      setConfirmArchive(null);
      await refresh();
    },
    onError: (error: unknown) => problemToast(error, "Couldn't archive the connection"),
  });

  if (connections.isLoading) {
    return (
      <div className="mt-6 space-y-3" data-testid="llm-connections-loading">
        <Skeleton className="h-9 w-40" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (connections.isError) {
    return (
      <div className="mt-6">
        <EmptyState
          icon={<AlertTriangle aria-hidden className="size-8" />}
          title="Couldn't load LLM connections"
          description="The list could not be fetched. This does not affect calls already in flight."
        >
          <Button variant="secondary" onClick={() => connections.refetch()}>
            Retry
          </Button>
        </EmptyState>
      </div>
    );
  }

  const items = ((connections.data as { items?: LlmConnection[] } | undefined)?.items ??
    []) as LlmConnection[];

  return (
    <div className="mt-6" data-testid="llm-connections-tab">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-medium">Model endpoints</h2>
          <p className="text-muted mt-1 text-xs">
            Every model call goes through the mesh, which enforces these settings.
          </p>
        </div>
        {canManage ? (
          <Button onClick={() => setPanel({ mode: "create" })} data-testid="add-llm-connection">
            <Plus aria-hidden className="size-4" /> Add connection
          </Button>
        ) : null}
      </div>

      {items.length === 0 ? (
        <div className="mt-4">
          <EmptyState
            icon={<Bot aria-hidden className="size-8" />}
            title="No model endpoints yet"
            description="Add one to let recipes and agents call a model. The built-in echo provider needs no credentials and never leaves this machine."
          >
            {canManage ? (
              <Button onClick={() => setPanel({ mode: "create" })}>Add connection</Button>
            ) : null}
          </EmptyState>
        </div>
      ) : (
        <Table className="mt-4">
          <THead>
            <TR>
              <TH>Name</TH>
              <TH>Provider</TH>
              <TH>Residency</TH>
              <TH>Audit</TH>
              <TH>Key</TH>
              <TH className="text-right">Actions</TH>
            </TR>
          </THead>
          <TBody>
            {items.map((connection) => (
              <TR key={connection.id} data-testid={`llm-connection-${connection.name}`}>
                <TD className="font-medium">
                  {connection.name}
                  {connection.scope === "global" ? (
                    <Badge variant="neutral" className="ml-2">
                      global
                    </Badge>
                  ) : null}
                </TD>
                <TD>
                  {connection.provider}
                  {connection.provider === "echo" ? (
                    // Never let a mock be mistaken for a real provider.
                    <Badge variant="neutral" className="ml-2">
                      mock
                    </Badge>
                  ) : null}
                </TD>
                <TD>
                  <ResidencyBadge residency={connection.data_residency} />
                </TD>
                <TD>
                  {connection.audit_mode === "full" ? (
                    <Badge variant="warning" title="Raw prompt text is retained">
                      full
                    </Badge>
                  ) : (
                    <span className="text-muted">{connection.audit_mode}</span>
                  )}
                </TD>
                <TD>
                  {connection.has_secret ? (
                    <span className="text-muted inline-flex items-center gap-1 text-xs">
                      <KeyRound aria-hidden className="size-3" /> set
                    </span>
                  ) : (
                    <span className="text-faint text-xs">—</span>
                  )}
                </TD>
                <TD className="text-right">
                  <div className="flex justify-end gap-2">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => test.mutate(connection.id)}
                      disabled={test.isPending}
                    >
                      Test
                    </Button>
                    {canManage && connection.scope !== "global" ? (
                      <>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setPanel({ mode: "edit", connection })}
                        >
                          Edit
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setConfirmArchive(connection)}
                        >
                          Archive
                        </Button>
                      </>
                    ) : null}
                  </div>
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      )}

      <QuotaSection projectKey={projectKey} canManage={canManage} />

      {panel ? (
        <ConnectionPanel
          projectKey={projectKey}
          state={panel}
          onClose={() => setPanel(null)}
          onSaved={async () => {
            setPanel(null);
            await refresh();
          }}
        />
      ) : null}

      <ConfirmDialog
        open={confirmArchive !== null}
        onOpenChange={(open) => !open && setConfirmArchive(null)}
        title="Archive this connection?"
        description="Calls already in the ledger keep pointing at it, so the history of what was sent where stays intact. New calls will be refused."
        confirmLabel="Archive"
        onConfirm={() => {
          if (confirmArchive) archive.mutate(confirmArchive.id);
        }}
      />
    </div>
  );
}

function ResidencyBadge({ residency }: { residency: string }) {
  const variant =
    residency === "local" ? "success" : residency === "eu" ? "info" : "warning";
  return (
    <Badge
      variant={variant}
      // The one thing an operator must not misread about this column.
      title="Operator-asserted: OSAIP enforces this declaration but cannot verify where a remote endpoint runs."
    >
      {residency}
    </Badge>
  );
}

function ConnectionPanel({
  projectKey,
  state,
  onClose,
  onSaved,
}: {
  projectKey: string;
  state: Exclude<PanelState, null>;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const editing = state.mode === "edit" ? state.connection : null;
  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: editing?.name ?? "",
      provider: (editing?.provider as (typeof PROVIDERS)[number]) ?? "echo",
      data_residency: (editing?.data_residency as (typeof RESIDENCIES)[number]) ?? "local",
      audit_mode: (editing?.audit_mode as (typeof AUDIT_MODES)[number]) ?? "redacted",
      allowed_models: editing?.allowed_models.join(", ") ?? "echo-1",
      base_url: "",
      cache_ttl_s: editing?.cache_ttl_s ?? 0,
      legal_basis: editing?.legal_basis ?? "",
      purpose_codes: editing?.purpose_codes.join(", ") ?? "",
      secret: "",
    },
  });

  const provider = form.watch("provider");
  const auditMode = form.watch("audit_mode");

  const save = useMutation({
    mutationFn: (values: FormValues) => {
      const parsed = schema.parse(values);
      const body = {
        name: parsed.name,
        base_config: parsed.base_url ? { base_url: parsed.base_url } : {},
        allowed_models: splitList(parsed.allowed_models),
        data_residency: parsed.data_residency,
        audit_mode: parsed.audit_mode,
        cache_ttl_s: parsed.cache_ttl_s,
        legal_basis: parsed.legal_basis,
        purpose_codes: splitList(parsed.purpose_codes),
        ...(parsed.secret ? { secret: parsed.secret } : {}),
      };
      return editing
        ? updateProjectConnection({
            path: { key: projectKey, connection_id: editing.id },
            body,
            throwOnError: true,
          })
        : createProjectConnection({
            path: { key: projectKey },
            body: { ...body, provider: parsed.provider },
            throwOnError: true,
          });
    },
    onSuccess: async () => {
      toast({ title: editing ? "Connection updated" : "Connection added", severity: "success" });
      await onSaved();
    },
    onError: (error: unknown) =>
      problemToast(error, editing ? "Couldn't save changes" : "Couldn't create the connection"),
  });

  return (
    <aside
      className="border-subtle bg-surface fixed inset-y-0 right-0 z-40 w-full max-w-md overflow-y-auto border-l p-6 shadow-lg"
      role="dialog"
      aria-label={editing ? "Edit LLM connection" : "Add LLM connection"}
      data-testid="llm-connection-panel"
    >
      <div className="flex items-start justify-between">
        <h3 className="text-base font-semibold">
          {editing ? `Edit ${editing.name}` : "Add model endpoint"}
        </h3>
        <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close">
          <X aria-hidden className="size-4" />
        </Button>
      </div>

      <form
        className="mt-6 space-y-4"
        onSubmit={form.handleSubmit((values) => save.mutate(values))}
      >
        <Field label="Name" error={form.formState.errors.name?.message}>
          <Input {...form.register("name")} autoFocus data-testid="llm-name" />
        </Field>

        {editing ? null : (
          <Field label="Provider">
            <NativeSelect {...form.register("provider")} data-testid="llm-provider">
              {PROVIDERS.map((value) => (
                <option key={value} value={value}>
                  {value}
                  {value === "echo" ? " (built-in mock)" : ""}
                </option>
              ))}
            </NativeSelect>
          </Field>
        )}

        <Field
          label="Data residency"
          error={form.formState.errors.data_residency?.message}
          hint="Operator-asserted. OSAIP enforces this declaration and audits it, but cannot verify where a remote endpoint actually runs — record the basis in your DPIA."
        >
          <NativeSelect {...form.register("data_residency")} data-testid="llm-residency">
            {RESIDENCIES.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </NativeSelect>
        </Field>

        {provider !== "echo" ? (
          <>
            <Field
              label="Base URL"
              hint="Leave empty for the vendor's own endpoint. A self-hosted endpoint on a private address must be allowlisted by the operator."
            >
              <Input {...form.register("base_url")} placeholder="https://…/v1" />
            </Field>
            <Field
              label={editing ? "Replace API key" : "API key"}
              hint="Write-only: it is encrypted at rest and never shown again, to anyone."
            >
              <Input type="password" {...form.register("secret")} autoComplete="off" />
            </Field>
          </>
        ) : null}

        <Field
          label="Allowed models"
          hint="Comma-separated. A model outside this list is refused before the provider is called."
        >
          <Input {...form.register("allowed_models")} data-testid="llm-models" />
        </Field>

        <Field label="Audit mode">
          <NativeSelect {...form.register("audit_mode")} data-testid="llm-audit-mode">
            <option value="redacted">redacted — store only redacted text (default)</option>
            <option value="full">full — also retain the raw prompt</option>
            <option value="off">off — store no message text</option>
          </NativeSelect>
        </Field>
        {auditMode === "full" ? (
          <p className="text-warning flex gap-2 text-xs" data-testid="audit-full-warning">
            <ShieldAlert aria-hidden className="size-4 shrink-0" />
            <span>
              Raw prompts — including any personal data in them — are retained alongside the
              redacted copy. Redaction still happens before the provider is called. Record this
              in your DPIA.
            </span>
          </p>
        ) : null}
        {auditMode === "off" ? (
          <p className="text-muted flex gap-2 text-xs">
            <ShieldAlert aria-hidden className="size-4 shrink-0" />
            <span>
              No prompt or response text is stored. Usage and cost are still ledgered, so budgets
              and reporting are unaffected.
            </span>
          </p>
        ) : null}

        <Field
          label="Cache TTL (seconds)"
          hint="0 disables caching. Cached answers are keyed on the redacted prompt and never cross projects."
        >
          <Input type="number" min={0} max={86400} {...form.register("cache_ttl_s")} />
        </Field>

        <Field
          label="Legal basis"
          error={form.formState.errors.legal_basis?.message}
          hint="CP-2: this endpoint is a processor; your RoPA needs the basis."
        >
          <Input {...form.register("legal_basis")} data-testid="llm-legal-basis" />
        </Field>
        <Field
          label="Purpose codes"
          error={form.formState.errors.purpose_codes?.message}
          hint="Comma-separated."
        >
          <Input {...form.register("purpose_codes")} data-testid="llm-purpose-codes" />
        </Field>

        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={save.isPending} data-testid="llm-save">
            {save.isPending ? "Saving…" : "Save"}
          </Button>
        </div>
      </form>
    </aside>
  );
}

function splitList(value: string): string[] {
  return value
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);
}

// ── budgets ────────────────────────────────────────────────────────────────────

type Quota = {
  id: string;
  period: string;
  limit_cost_micros: number | null;
  limit_calls: number | null;
  action: string;
};

function QuotaSection({
  projectKey,
  canManage,
}: {
  projectKey: string;
  canManage: boolean;
}) {
  const queryClient = useQueryClient();
  const quotas = useQuery(listQuotasOptions({ path: { key: projectKey } }));
  const [adding, setAdding] = useState(false);

  async function refresh() {
    await queryClient.invalidateQueries({
      queryKey: listQuotasQueryKey({ path: { key: projectKey } }),
    });
  }

  const create = useMutation({
    mutationFn: (body: {
      period: "day" | "month";
      limit_cost_micros?: number;
      limit_calls?: number;
      action: "warn" | "block";
    }) =>
      createQuota({ path: { key: projectKey }, body, throwOnError: true }),
    onSuccess: async () => {
      toast({ title: "Budget added", severity: "success" });
      setAdding(false);
      await refresh();
    },
    onError: (error: unknown) => problemToast(error, "Couldn't add the budget"),
  });

  const remove = useMutation({
    mutationFn: (quotaId: string) =>
      deleteQuota({ path: { key: projectKey, quota_id: quotaId }, throwOnError: true }),
    onSuccess: async () => {
      toast({ title: "Budget removed", severity: "info" });
      await refresh();
    },
    onError: (error: unknown) => problemToast(error, "Couldn't remove the budget"),
  });

  const items = ((quotas.data as { items?: Quota[] } | undefined)?.items ?? []) as Quota[];

  return (
    <section className="mt-10" data-testid="quota-section">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-medium">Budgets</h2>
          <p className="text-muted mt-1 text-xs">
            Enforced before the call reaches the provider. A blocking budget refuses; a warning
            budget notifies once and lets the call through.
          </p>
        </div>
        {canManage && !adding ? (
          <Button variant="secondary" onClick={() => setAdding(true)} data-testid="add-quota">
            <Gauge aria-hidden className="size-4" /> Add budget
          </Button>
        ) : null}
      </div>

      {quotas.isLoading ? (
        <Skeleton className="mt-4 h-20 w-full" />
      ) : items.length === 0 && !adding ? (
        <p className="text-muted mt-4 text-xs" data-testid="no-quotas">
          No budget set — model spend on this project is currently unbounded.
        </p>
      ) : (
        <Table className="mt-4">
          <THead>
            <TR>
              <TH>Period</TH>
              <TH>Cost limit</TH>
              <TH>Call limit</TH>
              <TH>When exceeded</TH>
              <TH className="text-right">Actions</TH>
            </TR>
          </THead>
          <TBody>
            {items.map((quota) => (
              <TR key={quota.id} data-testid={`quota-${quota.period}`}>
                <TD>{quota.period}</TD>
                <TD>{quota.limit_cost_micros === null ? "—" : formatEur(quota.limit_cost_micros)}</TD>
                <TD>{quota.limit_calls ?? "—"}</TD>
                <TD>
                  <Badge variant={quota.action === "block" ? "warning" : "neutral"}>
                    {quota.action}
                  </Badge>
                </TD>
                <TD className="text-right">
                  {canManage ? (
                    <Button variant="ghost" size="sm" onClick={() => remove.mutate(quota.id)}>
                      Remove
                    </Button>
                  ) : null}
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      )}

      {adding ? (
        <AddQuotaForm
          onCancel={() => setAdding(false)}
          onSubmit={(values) => create.mutate(values)}
          pending={create.isPending}
        />
      ) : null}
    </section>
  );
}

function AddQuotaForm({
  onCancel,
  onSubmit,
  pending,
}: {
  onCancel: () => void;
  onSubmit: (values: {
    period: "day" | "month";
    limit_cost_micros?: number;
    limit_calls?: number;
    action: "warn" | "block";
  }) => void;
  pending: boolean;
}) {
  const [period, setPeriod] = useState<"day" | "month">("month");
  const [euros, setEuros] = useState("10");
  const [calls, setCalls] = useState("");
  const [action, setAction] = useState<"warn" | "block">("block");

  return (
    <form
      className="border-subtle mt-4 flex flex-wrap items-end gap-3 rounded-md border p-4"
      onSubmit={(event) => {
        event.preventDefault();
        // Euros in the UI, integer micros on the wire — money never becomes a float.
        // Either limit alone is a valid budget; the server rejects having neither.
        onSubmit({
          period,
          ...(euros === "" ? {} : { limit_cost_micros: Math.round(Number(euros) * 1_000_000) }),
          ...(calls === "" ? {} : { limit_calls: Number(calls) }),
          action,
        });
      }}
    >
      <Field label="Period" className="w-32">
        <NativeSelect
          value={period}
          onChange={(e) => setPeriod(e.target.value as "day" | "month")}
        >
          <option value="day">day</option>
          <option value="month">month</option>
        </NativeSelect>
      </Field>
      <Field label="Limit (EUR)" className="w-32">
        <Input
          type="number"
          min={0}
          step="0.01"
          value={euros}
          onChange={(e) => setEuros(e.target.value)}
          data-testid="quota-eur"
        />
      </Field>
      <Field label="Call limit" className="w-32" hint="Optional">
        <Input
          type="number"
          min={0}
          value={calls}
          onChange={(e) => setCalls(e.target.value)}
          data-testid="quota-calls"
        />
      </Field>
      <Field label="When exceeded" className="w-40">
        <NativeSelect
          value={action}
          onChange={(e) => setAction(e.target.value as "warn" | "block")}
        >
          <option value="block">block the call</option>
          <option value="warn">warn and continue</option>
        </NativeSelect>
      </Field>
      <div className="flex gap-2">
        <Button type="button" variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={pending} data-testid="save-quota">
          Add
        </Button>
      </div>
    </form>
  );
}

export function formatEur(micros: number): string {
  return new Intl.NumberFormat("nl-NL", {
    style: "currency",
    currency: "EUR",
    // Model spend is often fractions of a cent; rounding to 2 would show every call
    // as €0.00 and make the panel useless.
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  }).format(micros / 1_000_000);
}

// Kept for the omnibar's connection lookup (object_refs surfaces these by name).
export { listProjectConnections };
