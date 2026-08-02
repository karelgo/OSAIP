// Usage panel: what the project actually spent, against the budgets that bound it.
// A budget nobody can see the spend against is not a control, which is why this sits
// next to the budgets rather than in a separate reporting corner.
//
// Costs arrive as integer micros and stay integers until the moment they are
// formatted — summing money as floats drifts over a month.
import {
  Badge,
  Button,
  EmptyState,
  Field,
  Skeleton,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "@osaip/ui";
import { getUsageOptions, listQuotasOptions } from "@osaip/api-client";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Info, TrendingUp } from "lucide-react";
import { useMemo, useState } from "react";
import { NativeSelect } from "../../lib/NativeSelect";
import { formatEur } from "./LlmConnectionsTab";

const GROUPINGS = ["day", "model", "user", "provider", "purpose"] as const;
type Grouping = (typeof GROUPINGS)[number];

const RANGES = [
  { label: "Last 7 days", days: 7 },
  { label: "Last 30 days", days: 30 },
  { label: "Last 90 days", days: 90 },
] as const;

type Bucket = {
  key: string;
  calls: number;
  tokens_in: number;
  tokens_out: number;
  cost_micros: number;
  cache_hits: number;
  errors: number;
};

type UsageReport = {
  from: string;
  to: string;
  group_by: string;
  currency: string;
  pricing_incomplete: boolean;
  total: Bucket;
  buckets: Bucket[];
};

type Quota = {
  id: string;
  period: string;
  limit_cost_micros: number | null;
  limit_calls: number | null;
  action: string;
};

export function UsageTab({ projectKey }: { projectKey: string }) {
  const [groupBy, setGroupBy] = useState<Grouping>("day");
  const [days, setDays] = useState(30);

  // Memoised, and quantised to the minute. Computing `new Date()` during render put a
  // fresh timestamp in the query key on every pass, so react-query refetched, which
  // re-rendered, which changed the key again — an infinite request loop against
  // /usage. Caught by e2e; it would have hammered the API in production.
  const { from, to } = useMemo(() => {
    const now = new Date();
    now.setSeconds(0, 0);
    return {
      to: now.toISOString(),
      from: new Date(now.getTime() - days * 24 * 60 * 60 * 1000).toISOString(),
    };
  }, [days]);

  const usage = useQuery(
    getUsageOptions({
      path: { key: projectKey },
      query: { group_by: groupBy, from, to },
    }),
  );
  const quotas = useQuery(listQuotasOptions({ path: { key: projectKey } }));

  if (usage.isLoading) {
    return (
      <div className="mt-6 space-y-3" data-testid="usage-loading">
        <Skeleton className="h-9 w-64" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }

  if (usage.isError) {
    return (
      <div className="mt-6">
        <EmptyState
          icon={<AlertTriangle aria-hidden className="size-8" />}
          title="Couldn't load usage"
          description="The rollup could not be fetched. Spend is still being recorded."
        >
          <Button variant="secondary" onClick={() => usage.refetch()}>
            Retry
          </Button>
        </EmptyState>
      </div>
    );
  }

  const report = usage.data as unknown as UsageReport;
  const quotaItems = ((quotas.data as { items?: Quota[] } | undefined)?.items ?? []) as Quota[];

  return (
    <div className="mt-6" data-testid="usage-panel">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-sm font-medium">Model usage</h2>
          <p className="text-muted mt-1 text-xs">
            Every call the mesh made for this project, including cached and failed ones.
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <Field label="Range" className="w-40">
            <NativeSelect
              value={String(days)}
              onChange={(event) => setDays(Number(event.target.value))}
              data-testid="usage-range"
            >
              {RANGES.map((range) => (
                <option key={range.days} value={range.days}>
                  {range.label}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <Field label="Group by" className="w-40">
            <NativeSelect
              value={groupBy}
              onChange={(event) => setGroupBy(event.target.value as Grouping)}
              data-testid="usage-group-by"
            >
              {GROUPINGS.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </NativeSelect>
          </Field>
        </div>
      </div>

      <dl className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-4" data-testid="usage-totals">
        <Stat label="Spend" value={formatEur(report.total.cost_micros)} />
        <Stat label="Calls" value={report.total.calls.toLocaleString("nl-NL")} />
        <Stat
          label="Tokens"
          value={(report.total.tokens_in + report.total.tokens_out).toLocaleString("nl-NL")}
        />
        <Stat
          label="Cache hits"
          value={report.total.cache_hits.toLocaleString("nl-NL")}
          hint={report.total.errors > 0 ? `${report.total.errors} failed` : undefined}
        />
      </dl>

      {report.pricing_incomplete ? (
        // An unpriced model contributes 0, so the total is a FLOOR. Saying so is the
        // difference between a report and a misleading one.
        <p className="text-muted mt-4 flex gap-2 text-xs" data-testid="pricing-incomplete">
          <Info aria-hidden className="size-4 shrink-0" />
          <span>
            Some calls used a model with no pinned price, so they count as €0. The total above
            is a lower bound, not the full spend.
          </span>
        </p>
      ) : null}

      {quotaItems.length > 0 ? (
        <section className="mt-8" data-testid="quota-bars">
          <h3 className="text-sm font-medium">Against budget</h3>
          <div className="mt-3 space-y-4">
            {quotaItems.map((quota) => (
              <QuotaBar key={quota.id} quota={quota} spent={report.total.cost_micros} />
            ))}
          </div>
          <p className="text-faint mt-2 text-xs">
            Spend shown is for the selected range; budgets run on calendar {""}
            {quotaItems.map((q) => q.period).join(" / ")} windows.
          </p>
        </section>
      ) : null}

      {report.buckets.length === 0 ? (
        <div className="mt-6">
          <EmptyState
            icon={<TrendingUp aria-hidden className="size-8" />}
            title="No model calls in this range"
            description="Once a recipe or an agent calls a model, its tokens and cost appear here."
          />
        </div>
      ) : (
        <Table className="mt-6">
          <THead>
            <TR>
              <TH>{groupBy}</TH>
              <TH className="text-right">Calls</TH>
              <TH className="text-right">Tokens in</TH>
              <TH className="text-right">Tokens out</TH>
              <TH className="text-right">Cost</TH>
              <TH className="text-right">Cached</TH>
              <TH className="text-right">Errors</TH>
            </TR>
          </THead>
          <TBody>
            {report.buckets.map((bucket) => (
              <TR key={bucket.key} data-testid={`usage-row-${bucket.key}`}>
                <TD className="font-medium">
                  {bucket.key === "unattributed" ? (
                    <span className="text-muted" title="A system call with no signed-in user">
                      unattributed
                    </span>
                  ) : (
                    bucket.key
                  )}
                </TD>
                <TD className="text-right tabular-nums">{bucket.calls}</TD>
                <TD className="text-right tabular-nums">{bucket.tokens_in.toLocaleString("nl-NL")}</TD>
                <TD className="text-right tabular-nums">
                  {bucket.tokens_out.toLocaleString("nl-NL")}
                </TD>
                <TD className="text-right tabular-nums">{formatEur(bucket.cost_micros)}</TD>
                <TD className="text-right tabular-nums">{bucket.cache_hits}</TD>
                <TD className="text-right tabular-nums">
                  {bucket.errors > 0 ? (
                    <Badge variant="warning">{bucket.errors}</Badge>
                  ) : (
                    <span className="text-faint">0</span>
                  )}
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      )}
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="border-subtle rounded-md border p-3">
      <dt className="text-muted text-xs">{label}</dt>
      <dd className="mt-1 text-lg font-semibold tabular-nums">{value}</dd>
      {hint ? <p className="text-warning mt-1 text-xs">{hint}</p> : null}
    </div>
  );
}

function QuotaBar({ quota, spent }: { quota: Quota; spent: number }) {
  const limit = quota.limit_cost_micros;
  if (limit === null || limit === 0) {
    return (
      <div data-testid={`quota-bar-${quota.period}`}>
        <div className="flex justify-between text-xs">
          <span className="font-medium">{quota.period} budget</span>
          <span className="text-muted">
            {quota.limit_calls !== null ? `${quota.limit_calls} calls` : "no cost limit"}
          </span>
        </div>
      </div>
    );
  }
  const ratio = Math.min(spent / limit, 1);
  const over = spent > limit;
  return (
    <div data-testid={`quota-bar-${quota.period}`}>
      <div className="flex justify-between text-xs">
        <span className="font-medium">{quota.period} budget</span>
        <span className={over ? "text-warning" : "text-muted"}>
          {formatEur(spent)} of {formatEur(limit)}
          {over ? ` — over (${quota.action})` : ""}
        </span>
      </div>
      <div
        className="bg-subtle mt-1 h-2 overflow-hidden rounded-full"
        role="progressbar"
        aria-valuenow={Math.round(ratio * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`${quota.period} budget used`}
      >
        <div
          className={over ? "bg-warning h-full" : "bg-accent h-full"}
          style={{ width: `${ratio * 100}%` }}
        />
      </div>
    </div>
  );
}
