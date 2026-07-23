// Per-kind recipe Configure forms (§6.3(10)): react-hook-form + zod, defaults-first
// with an Advanced accordion for the fiddly knobs. Each editor reads its config once,
// streams changes up (for the live Preview draft), and Saves explicitly via
// patchRecipe. SQL/Python swap the form body for lazy, self-hosted Monaco.
import { Button, Field, Input } from "@osaip/ui";
import type { RecipeOut } from "@osaip/api-client";
import { Plus, Trash2 } from "lucide-react";
import { Suspense, lazy, useEffect } from "react";
import { useFieldArray, useForm, type UseFormRegister } from "react-hook-form";

const CodeEditor = lazy(() => import("./CodeEditor"));

const TEXTAREA_CLASS =
  "flex w-full rounded-md border border-border bg-surface px-3 py-2 font-mono text-xs text-fg transition-colors duration-fast placeholder:text-faint focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg disabled:cursor-not-allowed disabled:opacity-50";

type Config = Record<string, unknown>;

export interface RecipeConfigFormProps {
  recipe: RecipeOut;
  initialConfig: Config;
  onChange: (config: Config) => void;
  onSave: (config: Config) => void;
  saving: boolean;
  canEdit: boolean;
  colorMode: "light" | "dark";
}

export function RecipeConfigForm(props: RecipeConfigFormProps) {
  switch (props.recipe.kind) {
    case "prepare":
      return <PrepareEditor {...props} />;
    case "join":
      return <JoinEditor {...props} />;
    case "group":
      return <GroupEditor {...props} />;
    case "split":
      return <SplitEditor {...props} />;
    case "sample":
      return <SampleEditor {...props} />;
    case "stack":
      return <StackEditor {...props} />;
    case "sql":
      return <CodeRecipeEditor {...props} field="query" language="sql" />;
    case "python":
      return <CodeRecipeEditor {...props} field="code" language="python" />;
    default:
      return (
        <p className="text-sm text-muted">This recipe kind has no editor yet.</p>
      );
  }
}

// ── Shared bits ────────────────────────────────────────────────────────────────────

function Advanced({ children }: { children: React.ReactNode }) {
  return (
    <details className="rounded-md border border-border">
      <summary className="cursor-pointer select-none px-3 py-2 text-sm font-medium text-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
        Advanced
      </summary>
      <div className="space-y-4 border-t border-border p-3">{children}</div>
    </details>
  );
}

function SaveRow({ saving, canEdit, dirty }: { saving: boolean; canEdit: boolean; dirty: boolean }) {
  if (!canEdit) return null;
  return (
    <Button type="submit" data-testid="recipe-save" loading={saving} disabled={!dirty}>
      Save changes
    </Button>
  );
}

/** Push the current config up on every change so the Preview tab can draft it. */
function useConfigStream(watch: () => unknown, toConfig: () => Config, onChange: (config: Config) => void) {
  useEffect(() => {
    onChange(toConfig());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [watch()]);
}

function parseList(raw: string): string[] {
  return raw
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
}

function parsePairs(raw: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const line of raw.split("\n")) {
    const index = line.indexOf("=");
    if (index === -1) continue;
    const key = line.slice(0, index).trim();
    const value = line.slice(index + 1).trim();
    if (key) out[key] = value;
  }
  return out;
}

function parsePairsTyped(raw: string): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(parsePairs(raw))) {
    try {
      out[key] = JSON.parse(value);
    } catch {
      out[key] = value;
    }
  }
  return out;
}

function pairsToLines(record: Record<string, unknown> | undefined): string {
  if (!record) return "";
  return Object.entries(record)
    .map(([key, value]) => `${key}=${typeof value === "string" ? value : JSON.stringify(value)}`)
    .join("\n");
}

// ── prepare ────────────────────────────────────────────────────────────────────────

type PrepareStep = {
  op: "rename" | "cast" | "filter" | "formula" | "fill_nulls" | "dedupe" | "select";
  lines?: string;
  expression?: string;
  column?: string;
  columns?: string;
  drop?: boolean;
};

interface PrepareValues {
  steps: PrepareStep[];
}

const STEP_OPS: Array<PrepareStep["op"]> = [
  "rename",
  "cast",
  "filter",
  "formula",
  "fill_nulls",
  "dedupe",
  "select",
];

function stepFromConfig(step: Record<string, unknown>): PrepareStep {
  const op = String(step.op) as PrepareStep["op"];
  switch (op) {
    case "rename":
      return { op, lines: pairsToLines(step.mapping as Record<string, unknown>) };
    case "cast":
      return { op, lines: pairsToLines(step.casts as Record<string, unknown>) };
    case "filter":
      return { op, expression: String(step.expression ?? "") };
    case "formula":
      return { op, column: String(step.column ?? ""), expression: String(step.expression ?? "") };
    case "fill_nulls":
      return { op, lines: pairsToLines(step.values as Record<string, unknown>) };
    case "dedupe":
      return { op, columns: ((step.subset as string[]) ?? []).join(", ") };
    case "select":
      return { op, columns: ((step.columns as string[]) ?? []).join(", "), drop: Boolean(step.drop) };
    default:
      return { op: "filter", expression: "" };
  }
}

function stepToConfig(step: PrepareStep): Config {
  switch (step.op) {
    case "rename":
      return { op: "rename", mapping: parsePairs(step.lines ?? "") };
    case "cast":
      return { op: "cast", casts: parsePairs(step.lines ?? "") };
    case "filter":
      return { op: "filter", expression: step.expression ?? "" };
    case "formula":
      return { op: "formula", column: step.column ?? "", expression: step.expression ?? "" };
    case "fill_nulls":
      return { op: "fill_nulls", values: parsePairsTyped(step.lines ?? "") };
    case "dedupe":
      return { op: "dedupe", subset: parseList(step.columns ?? "") };
    case "select":
      return { op: "select", columns: parseList(step.columns ?? ""), drop: Boolean(step.drop) };
  }
}

function PrepareEditor({ initialConfig, onChange, onSave, saving, canEdit }: RecipeConfigFormProps) {
  const initialSteps = ((initialConfig.steps as Array<Record<string, unknown>>) ?? []).map(stepFromConfig);
  const form = useForm<PrepareValues>({
    defaultValues: { steps: initialSteps.length > 0 ? initialSteps : [{ op: "filter", expression: "" }] },
  });
  const steps = useFieldArray({ control: form.control, name: "steps" });

  const toConfig = (): Config => ({
    kind: "prepare",
    steps: form.getValues().steps.map(stepToConfig),
  });
  useConfigStream(() => JSON.stringify(form.watch("steps")), toConfig, onChange);

  return (
    <form
      data-testid="recipe-config-form"
      className="space-y-4"
      onSubmit={form.handleSubmit(() => onSave(toConfig()))}
    >
      <ol className="space-y-3">
        {steps.fields.map((field, index) => {
          const op = form.watch(`steps.${index}.op`);
          return (
            <li key={field.id} className="rounded-md border border-border p-3">
              <div className="flex items-center justify-between gap-2">
                <select
                  aria-label={`Step ${index + 1} operation`}
                  disabled={!canEdit}
                  className="h-8 rounded-sm border border-border bg-surface px-2 text-xs"
                  {...form.register(`steps.${index}.op`)}
                >
                  {STEP_OPS.map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
                {canEdit && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    aria-label={`Remove step ${index + 1}`}
                    onClick={() => steps.remove(index)}
                  >
                    <Trash2 aria-hidden className="size-4" />
                  </Button>
                )}
              </div>
              <div className="mt-3 space-y-3">
                <StepFields op={op} index={index} register={form.register} canEdit={canEdit} />
              </div>
            </li>
          );
        })}
      </ol>
      {canEdit && (
        <Button
          type="button"
          variant="secondary"
          size="sm"
          onClick={() => steps.append({ op: "filter", expression: "" })}
        >
          <Plus aria-hidden className="size-4" /> Add step
        </Button>
      )}
      <div>
        <SaveRow saving={saving} canEdit={canEdit} dirty={form.formState.isDirty} />
      </div>
    </form>
  );
}

function StepFields({
  op,
  index,
  register,
  canEdit,
}: {
  op: PrepareStep["op"];
  index: number;
  register: UseFormRegister<PrepareValues>;
  canEdit: boolean;
}) {
  if (op === "rename" || op === "cast" || op === "fill_nulls") {
    const hint =
      op === "rename" ? "old=new" : op === "cast" ? "column=DUCKDB_TYPE" : "column=value (value as JSON)";
    return (
      <Field label="Mapping" hint={`One per line — ${hint}`}>
        <textarea rows={3} disabled={!canEdit} className={TEXTAREA_CLASS} {...register(`steps.${index}.lines`)} />
      </Field>
    );
  }
  if (op === "filter") {
    return (
      <Field label="Expression" hint='SQL predicate, e.g. col("revenue") > 0'>
        <Input disabled={!canEdit} className="font-mono" {...register(`steps.${index}.expression`)} />
      </Field>
    );
  }
  if (op === "formula") {
    return (
      <div className="grid grid-cols-2 gap-2">
        <Field label="New column">
          <Input disabled={!canEdit} className="font-mono" {...register(`steps.${index}.column`)} />
        </Field>
        <Field label="Expression" hint='e.g. col("a") * 0.3'>
          <Input disabled={!canEdit} className="font-mono" {...register(`steps.${index}.expression`)} />
        </Field>
      </div>
    );
  }
  if (op === "dedupe") {
    return (
      <Field label="Subset columns" hint="Comma-separated; empty = all columns">
        <Input disabled={!canEdit} className="font-mono" {...register(`steps.${index}.columns`)} />
      </Field>
    );
  }
  // select
  return (
    <div className="space-y-2">
      <Field label="Columns" hint="Comma-separated">
        <Input disabled={!canEdit} className="font-mono" {...register(`steps.${index}.columns`)} />
      </Field>
      <label className="flex items-center gap-2 text-sm text-muted">
        <input
          type="checkbox"
          disabled={!canEdit}
          className="size-4 rounded-sm border-border-strong text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          {...register(`steps.${index}.drop`)}
        />
        Drop these columns instead of keeping them
      </label>
    </div>
  );
}

// ── join ───────────────────────────────────────────────────────────────────────────

interface JoinValues {
  how: "inner" | "left" | "right" | "outer";
  on: Array<{ left: string; right: string }>;
  right_suffix: string;
}

function JoinEditor({ initialConfig, onChange, onSave, saving, canEdit }: RecipeConfigFormProps) {
  const form = useForm<JoinValues>({
    defaultValues: {
      how: (initialConfig.how as JoinValues["how"]) ?? "inner",
      on: ((initialConfig.on as JoinValues["on"]) ?? [{ left: "", right: "" }]),
      right_suffix: (initialConfig.right_suffix as string) ?? "_right",
    },
  });
  const on = useFieldArray({ control: form.control, name: "on" });
  const toConfig = (): Config => {
    const values = form.getValues();
    return { kind: "join", how: values.how, on: values.on, right_suffix: values.right_suffix };
  };
  useConfigStream(() => JSON.stringify(form.watch()), toConfig, onChange);

  return (
    <form
      data-testid="recipe-config-form"
      className="space-y-4"
      onSubmit={form.handleSubmit(() => onSave(toConfig()))}
    >
      <Field label="Join type">
        <select
          disabled={!canEdit}
          className="h-control w-full rounded-md border border-border bg-surface px-2.5 text-sm"
          {...form.register("how")}
        >
          {(["inner", "left", "right", "outer"] as const).map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
      </Field>
      <div className="space-y-2">
        <span className="text-sm font-medium">On keys</span>
        {on.fields.map((field, index) => (
          <div key={field.id} className="flex items-center gap-2">
            <Input
              disabled={!canEdit}
              placeholder="left column"
              className="font-mono"
              aria-label={`Left key ${index + 1}`}
              {...form.register(`on.${index}.left`)}
            />
            <span className="text-muted">=</span>
            <Input
              disabled={!canEdit}
              placeholder="right column"
              className="font-mono"
              aria-label={`Right key ${index + 1}`}
              {...form.register(`on.${index}.right`)}
            />
            {canEdit && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                aria-label={`Remove key ${index + 1}`}
                onClick={() => on.remove(index)}
              >
                <Trash2 aria-hidden className="size-4" />
              </Button>
            )}
          </div>
        ))}
        {canEdit && (
          <Button type="button" variant="secondary" size="sm" onClick={() => on.append({ left: "", right: "" })}>
            <Plus aria-hidden className="size-4" /> Add key
          </Button>
        )}
      </div>
      <Advanced>
        <Field label="Right suffix" hint="Appended to right-side columns that collide">
          <Input disabled={!canEdit} className="font-mono" {...form.register("right_suffix")} />
        </Field>
      </Advanced>
      <SaveRow saving={saving} canEdit={canEdit} dirty={form.formState.isDirty} />
    </form>
  );
}

// ── group ──────────────────────────────────────────────────────────────────────────

interface GroupValues {
  by: string;
  aggregations: Array<{ column: string; func: string; as: string }>;
}

const AGG_FUNCS = ["sum", "min", "max", "mean", "count", "count_distinct"] as const;

function GroupEditor({ initialConfig, onChange, onSave, saving, canEdit }: RecipeConfigFormProps) {
  const form = useForm<GroupValues>({
    defaultValues: {
      by: ((initialConfig.by as string[]) ?? []).join(", "),
      aggregations: ((initialConfig.aggregations as GroupValues["aggregations"]) ?? [
        { column: "", func: "sum", as: "" },
      ]),
    },
  });
  const aggregations = useFieldArray({ control: form.control, name: "aggregations" });
  const toConfig = (): Config => {
    const values = form.getValues();
    return { kind: "group", by: parseList(values.by), aggregations: values.aggregations };
  };
  useConfigStream(() => JSON.stringify(form.watch()), toConfig, onChange);

  return (
    <form
      data-testid="recipe-config-form"
      className="space-y-4"
      onSubmit={form.handleSubmit(() => onSave(toConfig()))}
    >
      <Field label="Group by" hint="Comma-separated columns">
        <Input disabled={!canEdit} className="font-mono" {...form.register("by")} />
      </Field>
      <div className="space-y-2">
        <span className="text-sm font-medium">Aggregations</span>
        {aggregations.fields.map((field, index) => (
          <div key={field.id} className="flex items-center gap-2">
            <Input
              disabled={!canEdit}
              placeholder="column"
              className="font-mono"
              aria-label={`Aggregation column ${index + 1}`}
              {...form.register(`aggregations.${index}.column`)}
            />
            <select
              disabled={!canEdit}
              aria-label={`Aggregation function ${index + 1}`}
              className="h-control rounded-md border border-border bg-surface px-2 text-sm"
              {...form.register(`aggregations.${index}.func`)}
            >
              {AGG_FUNCS.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
            <Input
              disabled={!canEdit}
              placeholder="as"
              className="font-mono"
              aria-label={`Aggregation alias ${index + 1}`}
              {...form.register(`aggregations.${index}.as`)}
            />
            {canEdit && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                aria-label={`Remove aggregation ${index + 1}`}
                onClick={() => aggregations.remove(index)}
              >
                <Trash2 aria-hidden className="size-4" />
              </Button>
            )}
          </div>
        ))}
        {canEdit && (
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => aggregations.append({ column: "", func: "sum", as: "" })}
          >
            <Plus aria-hidden className="size-4" /> Add aggregation
          </Button>
        )}
      </div>
      <SaveRow saving={saving} canEdit={canEdit} dirty={form.formState.isDirty} />
    </form>
  );
}

// ── split ──────────────────────────────────────────────────────────────────────────

function SplitEditor({ initialConfig, onChange, onSave, saving, canEdit }: RecipeConfigFormProps) {
  const form = useForm<{ expression: string }>({
    defaultValues: { expression: (initialConfig.expression as string) ?? "" },
  });
  const toConfig = (): Config => ({ kind: "split", expression: form.getValues().expression });
  useConfigStream(() => form.watch("expression"), toConfig, onChange);

  return (
    <form
      data-testid="recipe-config-form"
      className="space-y-4"
      onSubmit={form.handleSubmit(() => onSave(toConfig()))}
    >
      <Field label="Match expression" hint="Rows matching go to the first output; the rest to the second">
        <Input disabled={!canEdit} className="font-mono" {...form.register("expression")} />
      </Field>
      <SaveRow saving={saving} canEdit={canEdit} dirty={form.formState.isDirty} />
    </form>
  );
}

// ── sample ─────────────────────────────────────────────────────────────────────────

interface SampleValues {
  method: "head" | "random";
  n: string;
  fraction: string;
  seed: string;
}

function SampleEditor({ initialConfig, onChange, onSave, saving, canEdit }: RecipeConfigFormProps) {
  const form = useForm<SampleValues>({
    defaultValues: {
      method: (initialConfig.method as SampleValues["method"]) ?? "head",
      n: initialConfig.n === null || initialConfig.n === undefined ? "" : String(initialConfig.n),
      fraction:
        initialConfig.fraction === null || initialConfig.fraction === undefined
          ? ""
          : String(initialConfig.fraction),
      seed: initialConfig.seed === undefined ? "42" : String(initialConfig.seed),
    },
  });
  const toConfig = (): Config => {
    const values = form.getValues();
    const config: Config = { kind: "sample", method: values.method, seed: Number(values.seed) || 0 };
    config.n = values.n.trim() === "" ? null : Number(values.n);
    config.fraction = values.fraction.trim() === "" ? null : Number(values.fraction);
    return config;
  };
  useConfigStream(() => JSON.stringify(form.watch()), toConfig, onChange);

  return (
    <form
      data-testid="recipe-config-form"
      className="space-y-4"
      onSubmit={form.handleSubmit(() => onSave(toConfig()))}
    >
      <div className="grid grid-cols-2 gap-2">
        <Field label="Method">
          <select
            disabled={!canEdit}
            className="h-control w-full rounded-md border border-border bg-surface px-2.5 text-sm"
            {...form.register("method")}
          >
            <option value="head">head</option>
            <option value="random">random</option>
          </select>
        </Field>
        <Field label="Row count" hint="Leave blank to use a fraction">
          <Input disabled={!canEdit} type="number" inputMode="numeric" {...form.register("n")} />
        </Field>
      </div>
      <Advanced>
        <Field label="Fraction" hint="0–1; used when row count is blank">
          <Input disabled={!canEdit} type="number" step="0.01" {...form.register("fraction")} />
        </Field>
        <Field label="Seed" hint="Deterministic sampling seed">
          <Input disabled={!canEdit} type="number" inputMode="numeric" {...form.register("seed")} />
        </Field>
      </Advanced>
      <SaveRow saving={saving} canEdit={canEdit} dirty={form.formState.isDirty} />
    </form>
  );
}

// ── stack ──────────────────────────────────────────────────────────────────────────

function StackEditor({ onChange }: RecipeConfigFormProps) {
  useEffect(() => {
    onChange({ kind: "stack" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <p className="text-sm text-muted" data-testid="recipe-config-form">
      Stack unions every input by column name — missing columns fill with null. There's nothing to
      configure.
    </p>
  );
}

// ── sql / python ─────────────────────────────────────────────────────────────────────

function CodeRecipeEditor({
  initialConfig,
  onChange,
  onSave,
  saving,
  canEdit,
  colorMode,
  field,
  language,
}: RecipeConfigFormProps & { field: "query" | "code"; language: "sql" | "python" }) {
  const form = useForm<{ code: string }>({
    defaultValues: { code: (initialConfig[field] as string) ?? "" },
  });
  const toConfig = (): Config => ({ kind: language, [field]: form.getValues().code });
  useConfigStream(() => form.watch("code"), toConfig, onChange);

  return (
    <form
      data-testid="recipe-config-form"
      className="space-y-4"
      onSubmit={form.handleSubmit(() => onSave(toConfig()))}
    >
      <Suspense
        fallback={<div className="h-64 animate-pulse rounded-md border border-border bg-bg-subtle" />}
      >
        <CodeEditor
          data-testid="recipe-code-editor"
          value={form.watch("code")}
          language={language}
          colorMode={colorMode}
          readOnly={!canEdit}
          onChange={(value) => form.setValue("code", value, { shouldDirty: true })}
        />
      </Suspense>
      <SaveRow saving={saving} canEdit={canEdit} dirty={form.formState.isDirty} />
    </form>
  );
}
